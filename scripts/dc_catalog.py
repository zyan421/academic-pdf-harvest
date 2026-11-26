#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Digital Commons (bepress) 全量元数据目录采集器
================================================
用 OAI-PMH 的 document-export 格式批量取数，每条记录自带 fulltext-url（PDF 直链）。
每请求 100 条，比逐页抓文章页省 99% 的请求。

关键前提（缺一不可）：
  1. 必须清空 HTTP(S)_PROXY —— 本机 127.0.0.1:7899 会把这些站点掐断在 TLS 之后
  2. 必须用 curl_cffi + impersonate="chrome" —— 普通 requests/curl 会被 Cloudflare 挡
  3. fulltext-url 里是双重转义的 &amp;amp;，要连续 unescape 两次

用法：
  python dc_catalog.py                 # 采集全部仓储
  python dc_catalog.py --only Chicago  # 只采一个
  python dc_catalog.py --resume        # 断点续采（已完成的不重复）
"""
import os
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

import argparse
import html
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

from curl_cffi import requests as creq

NOPROXY = {"http": None, "https": None}
OUT_DIR = "dc_data"
JSONL_DIR = os.path.join(OUT_DIR, "jsonl")

# (短名, host, 期刊代码, 中文刊名)
REPOS = [
    ("Chicago",      "chicagounbound.uchicago.edu",            "uclrev",                 "芝加哥大学法律评论"),
    ("Duke",         "scholarship.law.duke.edu",               "dlj",                    "杜克法律杂志"),
    ("Michigan",     "repository.law.umich.edu",               "mlr",                    "密歇根法律评论"),
    ("Northwestern", "scholarlycommons.law.northwestern.edu",  "nulr",                   "西北大学法律评论"),
    ("Cornell",      "scholarship.law.cornell.edu",            "clr",                    "康奈尔法律评论"),
    ("CornellILJ",   "scholarship.law.cornell.edu",            "cilj",                   "康奈尔国际法杂志"),
    ("Fordham",      "ir.lawnet.fordham.edu",                  "flr",                    "福德姆法律评论"),
    ("WM",           "scholarship.law.wm.edu",                 "wmlr",                   "威廉与玛丽法律评论"),
    ("Emory",        "scholarlycommons.law.emory.edu",         "elj",                    "埃默里法律杂志"),
    ("NotreDame",    "scholarship.law.nd.edu",                 "ndlr",                   "圣母大学法律评论"),
    ("Vanderbilt",   "scholarship.law.vanderbilt.edu",         "vlr",                    "范德堡法律评论"),
    ("Florida",      "scholarship.law.ufl.edu",                "flr",                    "佛罗里达法律评论"),
    ("WUSTL",        "openscholarship.wustl.edu",              "law_lawreview",          "华盛顿大学法律评论"),
    ("UCLawSF",      "repository.uclawsf.edu",                 "hastings_law_journal",   "UC Law Journal（原 Hastings）"),
    ("BYU",          "digitalcommons.law.byu.edu",             "lawreview",              "杨百翰大学法律评论"),
    ("UWash",        "digitalcommons.law.uw.edu",              "wlr",                    "华盛顿法律评论"),
    ("UNC",          "scholarship.law.unc.edu",                "nclr",                   "北卡罗来纳法律评论"),
    ("Indiana",      "www.repository.law.indiana.edu",         "ilj",                    "印第安纳法律杂志"),
    ("BU",           "scholarship.law.bu.edu",                 "bulawreview",            "波士顿大学法律评论"),
]

_print_lock = threading.Lock()


def log(*a):
    with _print_lock:
        print(*a, flush=True)


def unescape2(s):
    return html.unescape(html.unescape(s or "")).strip()


def tag(block, name):
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S)
    return unescape2(m.group(1)) if m else ""


def parse_record(rec_xml, host, ctx, pubname):
    """一条 OAI record 可能含多个 <document>，逐个展开。"""
    ident = tag(rec_xml, "identifier")
    out = []
    for doc in re.findall(r"<document>(.*?)</document>", rec_xml, re.S):
        authors = []
        for a in re.findall(r"<author>(.*?)</author>", doc, re.S):
            ln, fn, mn = tag(a, "lname"), tag(a, "fname"), tag(a, "mname")
            nm = " ".join(x for x in [fn, mn, ln] if x).strip()
            if nm:
                authors.append(nm)
        title = tag(doc, "title")
        if not title:
            continue
        full = tag(doc, "fulltext-url")
        cover = tag(doc, "coverpage-url")
        pdate = tag(doc, "publication-date") or tag(doc, "submission-date")
        year = re.match(r"(\d{4})", pdate)
        # 卷期从 coverpage-url 的 submission-path 形态里取
        path = tag(doc, "submission-path")
        vm = re.search(r"/vol([^/]+)/iss([^/]+)/", "/" + path + "/") if path else None
        if not vm and cover:
            vm = re.search(r"/vol([^/]+)/iss([^/]+)/", cover)
        start_page = ""
        m = re.search(r'<field name="start_page"[^>]*>\s*<value>(.*?)</value>', doc, re.S)
        if m:
            start_page = unescape2(m.group(1))
        out.append({
            "source": ctx,
            "journal": pubname,
            "host": host,
            "oai_id": ident,
            "title": title,
            "authors": "; ".join(authors),
            "year": year.group(1) if year else "",
            "date": pdate[:10],
            "volume": vm.group(1) if vm else "",
            "issue": vm.group(2) if vm else "",
            "start_page": start_page,
            "doc_type": tag(doc, "document-type"),
            "article_id": tag(doc, "articleid"),
            "coverpage_url": cover,
            "pdf_url": full,
        })
    return out


def harvest(name, host, ctx, pubname, resume=True):
    os.makedirs(JSONL_DIR, exist_ok=True)
    path = os.path.join(JSONL_DIR, f"{name}.jsonl")
    if resume and os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, encoding="utf-8") as f:
            n = sum(1 for _ in f)
        log(f"[{name}] 已有 {n} 条，跳过（如需重采请删 {path}）")
        return name, host, ctx, n, None

    s = creq.Session(impersonate="chrome")
    total, written, pages, token = None, 0, 0, None
    t0 = time.time()
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        while True:
            params = {"verb": "ListRecords"}
            if token:
                params["resumptionToken"] = token
            else:
                params["metadataPrefix"] = "document-export"
                params["set"] = f"publication:{ctx}"
            url = f"https://{host}/do/oai/?{urlencode(params)}"
            try:
                r = s.get(url, timeout=120, proxies=NOPROXY)
            except Exception as e:
                log(f"[{name}] 第 {pages+1} 页异常 {type(e).__name__}，退避重试")
                time.sleep(8)
                s = creq.Session(impersonate="chrome")
                continue
            if r.status_code != 200:
                log(f"[{name}] 第 {pages+1} 页 HTTP {r.status_code}，换会话重试")
                time.sleep(6)
                s = creq.Session(impersonate="chrome")
                continue
            if total is None:
                m = re.search(r'completeListSize="(\d+)"', r.text)
                total = int(m.group(1)) if m else None
            err = re.search(r"<error[^>]*code=\"([^\"]+)\"", r.text)
            if err:
                log(f"[{name}] OAI 错误: {err.group(1)}")
                break
            recs = re.findall(r"<record>.*?</record>", r.text, re.S)
            for rec in recs:
                for item in parse_record(rec, host, ctx, pubname):
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                    written += 1
            pages += 1
            tm = re.search(r"<resumptionToken[^>]*>(.*?)</resumptionToken>", r.text, re.S)
            token = unescape2(tm.group(1)) if tm else None
            if pages % 10 == 0:
                el = time.time() - t0
                log(f"[{name}] {written}/{total or '?'} 条  {pages} 页  {el:.0f}s")
            if not token:
                break
            time.sleep(0.4)

    if written:
        os.replace(tmp, path)
    else:
        try:
            os.remove(tmp)
        except OSError:
            pass
    el = time.time() - t0
    log(f"[{name}] 完成 {written}/{total or '?'} 条，{pages} 页，{el:.0f}s")
    return name, host, ctx, written, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只采指定短名，逗号分隔")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args()

    targets = REPOS
    if args.only:
        want = {x.strip() for x in args.only.split(",")}
        targets = [r for r in REPOS if r[0] in want]
        if not targets:
            log("没有匹配的短名。可选：", ", ".join(r[0] for r in REPOS))
            sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)
    log(f"目标 {len(targets)} 家，并发 {args.workers}\n")
    summary = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(harvest, n, h, c, p, not args.no_resume): n for n, h, c, p in targets}
        for f in as_completed(futs):
            try:
                summary.append(f.result())
            except Exception as e:
                log(f"[{futs[f]}] 失败 {type(e).__name__}: {e}")
    summary.sort(key=lambda x: x[0])
    log("\n=== 汇总 ===")
    tt = 0
    for n, h, c, w, t in summary:
        tt += w
        log(f"  {n:14s} {w:>7,} 条")
    log(f"  合计 {tt:,} 条")
    json.dump([{"name": n, "host": h, "ctx": c, "written": w, "total": t} for n, h, c, w, t in summary],
              open(os.path.join(OUT_DIR, "harvest_summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
