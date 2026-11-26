#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Digital Commons PDF 批量下载器（v2：分站点限速 + 防重入）
==========================================================
读 dc_data/jsonl/*.jsonl（dc_catalog.py 的产物），按 manifest 断点续传下载。

四条硬约束（违反任一条都会失败）：
  1. 清空 HTTP(S)_PROXY —— 本机 127.0.0.1:7899 会把这些站点掐在 TLS 之后
  2. curl_cffi + impersonate="chrome" —— 唯一能过 Cloudflare 的组合
  3. PDF 请求绝不能带 Referer —— 带了必 403，不带反而 200
  4. 速率压在配额以下（每站点串行 + 每请求 12s）—— 慢即是快，实测零失败

v2 的关键改动：**限流是按站点的**。不同域名有独立配额，所以每个 host 一个线程、
一个限速闸门，跨站点并行不互相抢额度。

用法：
  python dc_download.py --journals Chicago,Duke --flat
  python dc_download.py --journals all --root "D:/法学期刊"
  python dc_download.py --journals Duke --preflight     # 只体检
  python dc_download.py --journals Duke --report        # 只报进度
  python dc_download.py --journals Duke --verify        # 核验已下载文件
"""
import os
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

import argparse
import glob
import json
import re
import sys
import threading
import time
import unicodedata
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from curl_cffi import requests as creq

NOPROXY = {"http": None, "https": None}
JSONL_DIR = os.path.join("dc_data", "jsonl")
DEFAULT_ROOT = os.path.join(os.path.expanduser("~"), "Downloads", "世界法学期刊PDF")
MIN_PDF_BYTES = 1024
SESS_BUDGET = 8           # 每会话请求数上限，到点重建
MAX_PATH = 235            # Windows 路径安全上限（留余量给 .part）
HB_STALE = 420            # 心跳超过这个秒数视为进程已死

_print_lock = threading.Lock()


def log(*a):
    with _print_lock:
        print(*a, flush=True)


def safe_name(s, maxlen=110):
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:maxlen].strip() or "untitled"


def rel_path(rec, root, flat=False):
    """刊名/卷/文件名。标题按剩余路径长度动态截断，避免撞 Windows 260 上限。

    同一期内常有同题条目（如 12 篇 "Tribute to ..."、"Post-Lecture Discussion"），
    直接落盘会互相覆盖。mark_duplicates() 会把这类记录打上 _dup 标记，
    这里再追加稳定的 article_id / CRC 后缀消歧。
    """
    j = safe_name(rec.get("journal") or rec.get("source"), 60)
    vol = rec.get("volume") or "noVol"
    vol_dir = f"v{int(vol):03d}" if str(vol).isdigit() else f"v{vol}"
    y = rec.get("year") or "n.d."
    iss = rec.get("issue") or "x"
    pg = rec.get("start_page") or ""

    parts = [y, f"vol{vol}", f"iss{iss}"]
    if pg:
        parts.append(f"p{pg}")
    prefix = "_".join(parts) + "_"

    suffix = ""
    if rec.get("_dup"):
        aid = str(rec.get("article_id") or "").strip()
        if not aid:
            aid = "%08x" % (zlib.crc32((rec.get("pdf_url") or "").encode()) & 0xFFFFFFFF)
        suffix = "_" + aid

    base_dir = os.path.join(root, vol_dir) if flat else os.path.join(root, j, vol_dir)
    budget = MAX_PATH - len(base_dir) - len(prefix) - len(suffix) - len(".pdf.part") - 1
    title = safe_name(rec.get("title"), max(budget, 20))
    fn = prefix + title + suffix + ".pdf"
    return os.path.join(base_dir, fn), os.path.join("" if flat else j, vol_dir, fn)


def mark_duplicates(recs, root, flat):
    """先算一遍目标路径，把会撞车的记录标记出来（就地修改 recs）。

    注意用 os.path.normcase 做键：Windows 文件系统大小写不敏感，
    "…the Forbidden Fruit" 与 "…The Forbidden Fruit" 字符串不同但会落成同一个文件。
    """
    groups = defaultdict(list)
    for r in recs:
        r.pop("_dup", None)
        groups[os.path.normcase(rel_path(r, root, flat)[0])].append(r)
    n = 0
    for path, rs in groups.items():
        if len(rs) > 1:
            for r in rs:
                r["_dup"] = True
                n += 1
    return n, sum(1 for rs in groups.values() if len(rs) > 1)


def host_of(rec):
    try:
        return urlsplit(rec["pdf_url"]).netloc.lower()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------- 限速与限流

class Governor:
    """单个站点的限速闸门。

    bepress 站点是「滑动窗口配额 + Retry-After」，实测约 50 篇 / 10 分钟。
    触发 429 后同一站点的所有线程必须一起停，并严格按 Retry-After 等待；
    边等边重试只会续期惩罚。把速率压在配额以下（约 5 篇/分钟）可做到零失败。
    """

    def __init__(self, host, min_interval=12.0):
        self.host = host
        self.lock = threading.Lock()
        self.until = 0.0
        self.min_interval = min_interval
        self.next_slot = 0.0
        self.hits = 0

    def wait(self):
        """占一个发送时隙，并真的等到该时隙。

        两个坑都在这里踩过：
        ① 只分配不等待 → 限速形同虚设；
        ② 在等待循环里重复分配时隙 → 间隔不断累加，5 篇能跑 6 分钟。
        正确做法：时隙只分配一次，循环里只等 max(时隙, 冷却截止)。
        """
        with self.lock:
            slot = max(time.time(), self.next_slot)
            self.next_slot = slot + self.min_interval
        while True:
            with self.lock:
                target = max(slot, self.until)
                delta = target - time.time()
            if delta <= 0:
                return
            time.sleep(min(delta, 5))

    def penalize(self, seconds, why="429"):
        with self.lock:
            self.hits += 1
            t = time.time() + seconds
            if t > self.until:
                self.until = t
                log(f"  [{self.host} 限流 {why}] 冷却 {seconds:.0f}s（第 {self.hits} 次）")


class SessState:
    """按线程维护 curl_cffi 会话，到预算就换新（Cloudflare 按会话累计计分）。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.local = threading.local()

    def _new(self):
        return creq.Session(impersonate="chrome")

    def _slot(self):
        if not hasattr(self.local, "s"):
            self.local.s = self._new()
            self.local.n = 0
        return self.local

    def get(self):
        return self._slot().s

    def tick(self):
        slot = self._slot()
        slot.n += 1
        if slot.n >= SESS_BUDGET:
            slot.s = self._new()
            slot.n = 0

    def rotate(self):
        slot = self._slot()
        with self.lock:
            slot.s = self._new()
            slot.n = 0


# ---------------------------------------------------------------- 单篇下载

def download_one(rec, root, state, gov, flat=False, ggov=None):
    dest, rel = rel_path(rec, root, flat)
    if os.path.exists(dest) and os.path.getsize(dest) >= MIN_PDF_BYTES:
        with open(dest, "rb") as f:
            if f.read(5) == b"%PDF-":
                return "skip", rel, os.path.getsize(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    url = rec["pdf_url"]
    partial = dest + ".part"
    last = 0

    for attempt in range(5):
        if ggov:                    # 全局限速：bepress 的配额是 IP 级的，跨站共享
            ggov.wait()
        gov.wait()
        s = state.get()
        try:
            # 绝不能带 Referer：bepress 的 Cloudflare 规则对带 Referer 的请求直接 403
            r = s.get(url, timeout=240, proxies=NOPROXY)
            state.tick()
        except Exception:
            state.rotate()
            time.sleep(5 + attempt * 5)
            continue

        if r.status_code == 200 and r.content[:5] == b"%PDF-":
            if len(r.content) < MIN_PDF_BYTES:
                return "tiny", rel, len(r.content)
            with open(partial, "wb") as f:
                f.write(r.content)
            os.replace(partial, dest)
            return "ok", rel, len(r.content)

        if r.status_code == 429:
            last = 429
            ra = r.headers.get("retry-after") or ""
            try:
                wait = float(ra)
            except ValueError:
                wait = 120.0 * (attempt + 1)
            gov.penalize(wait + 15, "429")
            if ggov:                # 配额是 IP 全局的，一个站触发要全体停
                ggov.penalize(wait + 15, f"429@{gov.host.split('.')[0]}")
            state.rotate()
            continue

        if r.status_code == 403:
            last = 403
            gov.penalize(20 + attempt * 10, "403")
            state.rotate()
            continue

        if r.status_code in (404, 410):
            return "missing", rel, r.status_code

        last = r.status_code
        time.sleep(5 + attempt * 5)
        state.rotate()

    return "fail", rel, f"HTTP {last}" if last else url


# ---------------------------------------------------------------- 数据与统计

def load_records(journals):
    recs, seen = [], set()
    for p in sorted(glob.glob(os.path.join(JSONL_DIR, "*.jsonl"))):
        name = os.path.basename(p)[:-6]
        if journals and name not in journals:
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                u = r.get("pdf_url")
                if not u or u in seen:
                    continue
                seen.add(u)
                r["_journal_key"] = name
                recs.append(r)
    return recs


def raw_count(journals):
    n = 0
    for p in sorted(glob.glob(os.path.join(JSONL_DIR, "*.jsonl"))):
        if journals and os.path.basename(p)[:-6] not in journals:
            continue
        n += sum(1 for l in open(p, encoding="utf-8") if l.strip())
    return n


def do_preflight(recs, root, flat, journals):
    ndup, ngroups = mark_duplicates(recs, root, flat)
    paths = [rel_path(r, root, flat)[0] for r in recs]
    c = Counter(os.path.normcase(p) for p in paths)
    col = [p for p, k in c.items() if k > 1]
    L = [len(p) for p in paths]
    raw = raw_count(journals)
    log("\n=== 下载前体检 ===")
    log(f"  记录总数        : {raw:,}")
    log(f"  缺 PDF 直链     : {raw - len(recs):,}")
    log(f"  待下载（去重后）: {len(recs):,}")
    log(f"  同题冲突        : {ngroups} 组 / {ndup} 条 → 已自动加 article_id 后缀消歧")
    if col:
        log(f"  仍有未消解碰撞  : {len(col)} 组（需人工检查）")
        for p in col[:5]:
            log(f"     {c[p]}x  {os.path.basename(p)[-76:]}")
    if L:
        log(f"  路径长度 最长/均值: {max(L)} / {sum(L)//len(L)}")
        log(f"  超 {MAX_PATH} 的条数 : {sum(1 for x in L if x > MAX_PATH)}")
    hosts = Counter(host_of(r) for r in recs)
    log(f"  涉及站点 {len(hosts)} 个（每站独立限速，可并行）:")
    for h, n in hosts.most_common():
        log(f"     {n:>6,}  {h}")


def do_report(recs, root, flat, title="下载进度"):
    have, size, bad = 0, 0, 0
    byj = defaultdict(lambda: [0, 0, 0])   # [有, 总, 字节]
    for r in recs:
        dest, _ = rel_path(r, root, flat)
        k = r.get("_journal_key") or r.get("journal")
        byj[k][1] += 1
        ok = False
        if os.path.exists(dest):
            sz = os.path.getsize(dest)
            if sz >= MIN_PDF_BYTES:
                with open(dest, "rb") as f:
                    ok = f.read(5) == b"%PDF-"
                if ok:
                    have += 1
                    size += sz
                    byj[k][0] += 1
                    byj[k][2] += sz
        if os.path.exists(dest) and not ok:
            bad += 1
    log(f"\n=== {title} ===")
    log(f"  {'期刊':<22}{'已完成':>8}{'总数':>8}{'完成率':>8}{'体积':>10}")
    for k in sorted(byj, key=lambda x: -byj[x][1]):
        h, t, b = byj[k]
        log(f"  {str(k):<22}{h:>8,}{t:>8,}{(h/t*100 if t else 0):>7.1f}%{b/1073741824:>9.2f}G")
    tot = sum(v[1] for v in byj.values())
    log(f"  {'合计':<22}{have:>8,}{tot:>8,}{(have/tot*100 if tot else 0):>7.1f}%{size/1073741824:>9.2f}G")
    if bad:
        log(f"  异常文件（存在但非 PDF）: {bad}")
    return have, tot


def do_verify(root):
    ok, bad, part = 0, [], []
    for dirpath, _, files in os.walk(root):
        for fn in files:
            fp = os.path.join(dirpath, fn)
            if fn.endswith(".part"):
                part.append(fp)
                continue
            if not fn.lower().endswith(".pdf"):
                continue
            try:
                with open(fp, "rb") as f:
                    if f.read(5) == b"%PDF-":
                        ok += 1
                    else:
                        bad.append(fp)
            except OSError:
                bad.append(fp)
    log(f"\n=== 文件核验 ===\n  真 PDF : {ok:,}\n  非 PDF : {len(bad)}\n  .part 残留: {len(part)}")
    for p in bad[:10]:
        log("   坏:", p)


# ---------------------------------------------------------------- 防重入

def acquire_lock(root):
    """用心跳文件防止同一目录被两个进程同时下载（会互相抢配额）。"""
    os.makedirs(root, exist_ok=True)
    hb = os.path.join(root, ".dc_download.heartbeat")
    if os.path.exists(hb) and time.time() - os.path.getmtime(hb) < HB_STALE:
        return None
    with open(hb, "w", encoding="utf-8") as f:
        f.write(f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}")
    return hb


def heartbeat_loop(hb, stop):
    while not stop.is_set():
        try:
            os.utime(hb, None)
        except OSError:
            pass
        stop.wait(60)


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journals", default="all", help="短名逗号分隔，或 all")
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--year-from", type=int)
    ap.add_argument("--year-to", type=int)
    ap.add_argument("--limit", type=int, help="每刊最多下载多少篇（试跑用）")
    ap.add_argument("--order", choices=["new", "old", "vol"], default="new")
    ap.add_argument("--flat", action="store_true",
                    help="单刊下载时 root 目录本身就是刊目录，不再套一层刊名")
    ap.add_argument("--min-interval", type=float, default=12.0,
                    help="同一站点两次请求的最小间隔（秒）。默认 12s≈300篇/小时")
    ap.add_argument("--global-interval", type=float, default=1.6,
                    help="所有站点合计的最小请求间隔（秒）。bepress 配额是 IP 全局的，"
                         "默认 1.6s≈0.63篇/秒，是实测安全值；设 0 关闭全局限速")
    ap.add_argument("--per-host", type=int, default=1,
                    help="每个站点并发线程数。默认 1；设 2 会成倍消耗配额并触发 429")
    ap.add_argument("--max-hosts", type=int, default=8, help="同时并行的站点数上限")
    ap.add_argument("--preflight", action="store_true", help="只做下载前体检")
    ap.add_argument("--report", action="store_true", help="只报进度，不下载")
    ap.add_argument("--verify", action="store_true", help="只核验已下载文件")
    ap.add_argument("--force", action="store_true", help="无视防重入锁强行启动")
    args = ap.parse_args()

    avail = sorted(os.path.basename(p)[:-6] for p in glob.glob(os.path.join(JSONL_DIR, "*.jsonl")))
    if not avail:
        log("没有 jsonl 数据，先跑 dc_catalog.py")
        sys.exit(1)
    journals = None if args.journals == "all" else {x.strip() for x in args.journals.split(",") if x.strip()}
    if journals:
        miss = journals - set(avail)
        if miss:
            log("未知短名:", ", ".join(miss), "\n可选:", ", ".join(avail))
            sys.exit(1)

    recs = load_records(journals)
    if args.year_from:
        recs = [r for r in recs if r.get("year") and int(r["year"]) >= args.year_from]
    if args.year_to:
        recs = [r for r in recs if r.get("year") and int(r["year"]) <= args.year_to]

    root = os.path.abspath(args.root)

    def ykey(r):
        y = r.get("year")
        return int(y) if y and str(y).isdigit() else 0

    if args.order == "new":
        recs.sort(key=lambda r: (-ykey(r), r["_journal_key"]))
    elif args.order == "old":
        recs.sort(key=lambda r: (ykey(r), r["_journal_key"]))

    if args.limit:          # 必须在排序之后，否则取到的是文件顺序前 N 条
        byj, lim = {}, []
        for r in recs:
            k = r["_journal_key"]
            byj.setdefault(k, 0)
            if byj[k] < args.limit:
                byj[k] += 1
                lim.append(r)
        recs = lim

    if args.verify:
        do_verify(root)
        return
    if args.report:
        mark_duplicates(recs, root, args.flat)
        do_report(recs, root, args.flat)
        return
    if args.preflight:
        do_preflight(recs, root, args.flat, journals)
        return

    mark_duplicates(recs, root, args.flat)   # 保证下载与报告用的是同一套文件名
    log(f"待处理 {len(recs):,} 篇 → {root}")

    if args.force:
        os.makedirs(root, exist_ok=True)
        hb = os.path.join(root, ".dc_download.heartbeat")
        with open(hb, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')} forced")
    else:
        hb = acquire_lock(root)
        if hb is None:
            log("检测到另一个下载进程仍在运行（心跳未过期），本次退出。")
            log("确有需要请加 --force，或删除 .dc_download.heartbeat 后重试。")
            sys.exit(2)

    by_host = defaultdict(list)
    for r in recs:
        by_host[host_of(r)].append(r)
    hosts = sorted(by_host.items(), key=lambda x: -len(x[1]))[:args.max_hosts]
    if len(by_host) > args.max_hosts:
        log(f"注意：站点数 {len(by_host)} 超过 --max-hosts={args.max_hosts}，本轮只处理前 {args.max_hosts} 个")
    log(f"站点 {len(hosts)} 个，每站 {args.per_host} 线程，间隔 {args.min_interval}s")
    for h, rs in hosts:
        log(f"   {len(rs):>6,}  {h}")

    stats = Counter()
    counter = {"bytes": 0, "done": 0}
    t0 = time.time()
    manifest = os.path.join(root, "_manifest.jsonl")
    mlock = threading.Lock()
    stop = threading.Event()
    total_tasks = sum(len(v) for _, v in hosts)

    # 全局限速闸门：bepress 的配额按 IP 计，跨站点共享，12 站齐发会瞬间越线
    ggov = Governor("ALL", args.global_interval) if args.global_interval > 0 else None
    if ggov:
        log(f"全局限速：每 {args.global_interval}s 最多 1 个请求（约 {1/args.global_interval:.2f} 篇/秒）")

    if hb:
        threading.Thread(target=heartbeat_loop, args=(hb, stop), daemon=True).start()

    def host_worker(host, rs, mfh):
        gov = Governor(host, args.min_interval)
        st = SessState()
        for r in rs:
            d, rel, extra = download_one(r, root, st, gov, args.flat, ggov)
            with mlock:
                stats[d] += 1
                counter["done"] += 1
                if d == "ok":
                    counter["bytes"] += extra
                mfh.write(json.dumps(
                    {"status": d, "journal": r["_journal_key"], "file": rel,
                     "bytes": extra if d == "ok" else None,
                     "reason": None if d in ("ok", "skip") else str(extra),
                     "url": r["pdf_url"] if d in ("fail", "exc") else None},
                    ensure_ascii=False) + "\n")
                mfh.flush()
                if counter["done"] % 20 == 0 or d in ("fail", "exc"):
                    el = time.time() - t0
                    rate = counter["done"] / el if el else 0
                    eta = (total_tasks - counter["done"]) / rate / 3600 if rate else 0
                    log(f"  {counter['done']}/{total_tasks}  ok={stats['ok']} skip={stats['skip']} "
                        f"fail={stats['fail']} miss={stats['missing']}  "
                        f"{counter['bytes']/1048576:.0f}MB  {rate:.2f}篇/s  ETA {eta:.1f}h")

    with open(manifest, "a", encoding="utf-8") as mfh, \
         ThreadPoolExecutor(max_workers=len(hosts) * max(args.per_host, 1)) as ex:
        futs = []
        for h, rs in hosts:
            futs.append(ex.submit(host_worker, h, rs, mfh))
        for f in futs:
            try:
                f.result()
            except Exception as e:
                log("  站点线程异常:", type(e).__name__, str(e)[:80])

    stop.set()
    log("\n=== 完成 ===")
    for k, v in stats.most_common():
        log(f"  {k:8s} {v:,}")
    log(f"  体积 {counter['bytes']/1073741824:.2f} GB，耗时 {(time.time()-t0)/60:.1f} 分钟")
    do_report(recs, root, args.flat)
    do_verify(root)


if __name__ == "__main__":
    main()
