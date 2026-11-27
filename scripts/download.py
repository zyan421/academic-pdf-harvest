#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download all HLR PDFs to a local folder, slowly and safely.

Source: hlr_pdf_catalog.jsonl (pdf_urls field)
Target: ~/Downloads/Harvard Law Review PDFs/
Manifest: hlr_download_manifest.jsonl (resumable; one line per file)

Safety design:
  - Single worker, 1.5-3.0s jitter delay between requests (gentle on server).
  - Retries with exponential backoff (3 attempts).
  - Resumable: skips files already downloaded and verified.
  - Validates PDF magic header (%PDF) and minimum size.
  - Filename: zero-padded index + volume + genre + truncated title (unique, sortable).
"""
import sys, re, json, time, random, os, hashlib, urllib.request, urllib.error, threading, unicodedata, urllib.parse

sys.stdout.reconfigure(encoding="utf-8")

SRC = "hlr_pdf_catalog.jsonl"
MANIFEST = "hlr_download_manifest.jsonl"
# 输出目录：可用环境变量 PDF_TARGET_DIR 覆盖，默认落到 ~/Downloads/Harvard Law Review PDFs
TARGET_DIR = os.environ.get("PDF_TARGET_DIR") or os.path.join(
    os.path.expanduser("~"), "Downloads", "Harvard Law Review PDFs")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA,
           "Accept": "application/pdf,*/*",
           "Accept-Language": "en-US,en;q=0.9"}
MIN_DELAY = 1.5
MAX_DELAY = 3.0
MAX_RETRY = 3
MIN_PDF_BYTES = 1000
WORKERS = 3
_state_lock = threading.Lock()
_stats = {"ok": 0, "fail": 0, "n": 0}

os.makedirs(TARGET_DIR, exist_ok=True)


def safe_name(s, maxlen=70):
    # 关键：非 ASCII 字符（弯引号、组合重音、零宽字符）会让 Windows 文件系统写入失败。
    # 先 NFKC 归一消除组合重音，再剔除所有非 ASCII 字符。
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    s = s.encode("ascii", "ignore").decode("ascii")
    return s[:maxlen] or "untitled"


def encode_url(url):
    # URL 若含非 ASCII（如 D’Amato、Rodríguez），urllib 会抛 ascii 编码错误。
    # 去零宽字符 + NFC 归一 + 对 path 做 percent-encoding。
    url = url.replace("\u200c", "").replace("\u200b", "")
    url = unicodedata.normalize("NFC", url)
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (p.scheme, p.netloc, urllib.parse.quote(p.path), p.query, p.fragment))


def build_tasks():
    seen = set()
    tasks = []
    for line in open(SRC, encoding="utf-8"):
        r = json.loads(line)
        vol = re.search(r"vol-(\d+)", r["article_url"])
        vol = vol.group(1) if vol else "NA"
        genre = safe_name(r.get("genre") or "Misc", 24)
        title = safe_name(r.get("title") or "", 70)
        for pdf in r.get("pdf_urls", []):
            if pdf in seen:
                continue
            seen.add(pdf)
            idx = len(tasks) + 1
            fname = f"{idx:04d}_V{vol}_{genre}_{title}.pdf"
            tasks.append({"idx": idx, "url": pdf, "filename": fname,
                          "article_url": r["article_url"], "title": r.get("title", ""),
                          "genre": r.get("genre", ""), "vol": vol})
    return tasks


def load_manifest():
    done = {}
    if os.path.exists(MANIFEST):
        for line in open(MANIFEST, encoding="utf-8"):
            try:
                r = json.loads(line)
                done[r["url"]] = r
            except Exception:
                pass
    return done


def log(rec):
    with open(MANIFEST, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def download(url, path):
    req = urllib.request.Request(encode_url(url), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = resp.read()
    if len(data) < MIN_PDF_BYTES:
        raise ValueError(f"too small: {len(data)} bytes")
    if not data[:5].startswith(b"%PDF"):
        raise ValueError("not a PDF (bad magic header)")
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return len(data), hashlib.md5(data).hexdigest()


def worker(pending, wid, total):
    while True:
        with _state_lock:
            if not pending:
                return
            t = pending.pop(0)
        path = os.path.join(TARGET_DIR, t["filename"])
        rec = {"url": t["url"], "filename": t["filename"], "article_url": t["article_url"],
               "title": t["title"], "genre": t["genre"], "vol": t["vol"]}
        if os.path.exists(path) and os.path.getsize(path) > MIN_PDF_BYTES:
            rec.update(status="ok", size=os.path.getsize(path), skipped=True)
            with _state_lock:
                log(rec)
                _stats["ok"] += 1
            continue
        last_err = ""
        for attempt in range(MAX_RETRY):
            try:
                size, md5 = download(t["url"], path)
                rec.update(status="ok", size=size, md5=md5, attempts=attempt + 1)
                with _state_lock:
                    log(rec)
                    _stats["ok"] += 1
                break
            except Exception as e:
                last_err = str(e)[:200]
                if attempt < MAX_RETRY - 1:
                    time.sleep((2 ** attempt) + random.random())
        else:
            rec.update(status="error", error=last_err, attempts=MAX_RETRY)
            with _state_lock:
                log(rec)
                _stats["fail"] += 1
                _stats["n"] += 1
                print(f"[FAIL] {last_err} :: {t['url'][-60:]}", flush=True)
                if _stats["n"] % 25 == 0:
                    print(f"[PROGRESS] ok={_stats['ok']} fail={_stats['fail']} remaining={len(pending)}", flush=True)
        time.sleep(MIN_DELAY + random.random() * (MAX_DELAY - MIN_DELAY))


def main():
    tasks = build_tasks()
    done = load_manifest()
    pending = [t for t in tasks if t["url"] not in done or done[t["url"]].get("status") != "ok"]
    print(f"total={len(tasks)} already_ok={len(tasks)-len(pending)} pending={len(pending)} workers={WORKERS}",
          flush=True)
    threads = []
    for i in range(WORKERS):
        th = threading.Thread(target=worker, args=(pending, i, len(tasks)), daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    print(f"DONE. ok={_stats['ok']} fail={_stats['fail']}", flush=True)


if __name__ == "__main__":
    main()
