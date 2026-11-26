#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Harvest PDF direct URLs from all Harvard Law Review article pages.

Inputs:  hlr_all_urls.json  (list of article URLs from sitemaps)
Output:  hlr_pdf_catalog.jsonl  (one JSON object per line, resumable)

Strategy:
  - Only PRINT and FORUM pages carry article-specific PDFs; BLOG pages do not.
  - 4 workers with jitter delay to avoid Cloudflare throttling.
  - Resume-safe: skips URLs already present in the output file.
  - Retries failed pages up to 3 times with backoff.
"""
import sys, re, json, time, random, threading, urllib.request, urllib.error, os, html

sys.stdout.reconfigure(encoding="utf-8")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
OUT = "hlr_pdf_catalog.jsonl"
WORKERS = 4
DELAY = 0.8
MAX_RETRY = 3

lock = threading.Lock()
done = set()
if os.path.exists(OUT):
    for line in open(OUT, encoding="utf-8"):
        try:
            done.add(json.loads(line)["article_url"])
        except Exception:
            pass


def kind(u):
    if re.search(r"/print/vol-\d+/[^/]+/$", u): return "Print"
    if re.search(r"/forum/vol-\d+/[^/]+/$", u): return "Forum"
    if re.search(r"/blog/\d{4}/\d{2}/[^/]+/$", u): return "Blog"
    return "Other"


def fetch(u):
    req = urllib.request.Request(u, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read().decode("utf-8", "ignore")


def extract(page):
    pdfs = re.findall(r'https://harvardlawreview\.org/wp-content/uploads/[^"\'<> ]+?\.pdf', page)
    pdfs = [p for p in pdfs if "Factsheet" not in p]
    pdfs = list(dict.fromkeys(pdfs))
    m = re.search(r"<title>(.*?)</title>", page, re.S)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    title = html.unescape(title)
    title = re.sub(r"\s*\|?\s*Harvard Law Review\s*$", "", title).strip()
    m = re.search(r"(\d{3})\s+Harv\.\s+L\.\s+Rev\.\s+(\d+)", page)
    cite = f"{m.group(1)} Harv. L. Rev. {m.group(2)}" if m else ""
    # 文章自身的栏目（piece type）与主题（topic），从 header 区域精确提取
    piece = re.search(r'single-article__piece-type[^>]*>\s*<a[^>]*>(.*?)</a>', page, re.S)
    genre = html.unescape(re.sub(r"<[^>]+>", "", piece.group(1))).strip() if piece else ""
    topic_m = re.search(r'single-article__topic[^>]*>\s*<a[^>]*>(.*?)</a>', page, re.S)
    topic = html.unescape(re.sub(r"<[^>]+>", "", topic_m.group(1))).strip() if topic_m else ""
    # 作者：single-article__author 区域
    authors = re.findall(r'single-article__author[^>]*>\s*<a[^>]*>(.*?)</a>', page, re.S)
    authors = [html.unescape(re.sub(r"<[^>]+>", "", a)).strip() for a in authors]
    return {"pdf_urls": pdfs, "title": title, "cite": cite,
            "genre": genre, "topic": topic, "authors": authors}


def worker(urls, tid, counter):
    while True:
        with lock:
            if not urls:
                return
            u = urls.pop(0)
        if u in done:
            continue
        rec = {"article_url": u, "kind": kind(u)}
        for attempt in range(MAX_RETRY):
            try:
                page = fetch(u)
                info = extract(page)
                rec.update(info)
                rec["status"] = "ok" if info["pdf_urls"] else "no_pdf"
                rec["html_len"] = len(page)
                break
            except Exception as e:
                rec["status"] = "error"
                rec["error"] = str(e)[:200]
                if attempt < MAX_RETRY - 1:
                    time.sleep(2 ** attempt + random.random())
        with lock:
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done.add(u)
            counter[0] += 1
            if counter[0] % 50 == 0:
                print(f"[{tid}] processed {counter[0]} (cached {len(done)})", file=sys.stderr, flush=True)
        time.sleep(DELAY + random.random() * 0.6)


def main():
    all_urls = json.load(open("hlr_all_urls.json", encoding="utf-8"))
    targets = [u for u in all_urls if kind(u) in ("Print", "Forum")]
    pending = [u for u in targets if u not in done]
    print(f"Total targets={len(targets)}, already done={len(targets)-len(pending)}, pending={len(pending)}",
          file=sys.stderr, flush=True)
    counter = [0]
    threads = []
    for i in range(WORKERS):
        t = threading.Thread(target=worker, args=(pending, i, counter), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    print(f"DONE. processed {counter[0]} this run.", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
