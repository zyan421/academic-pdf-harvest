#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retry failed HLR PDF downloads with URL fixes and article-page re-extraction."""
import sys, re, json, os, html, time, random, urllib.request

sys.stdout.reconfigure(encoding="utf-8")

from hlr_download import (MANIFEST, TARGET_DIR, HEADERS, MIN_DELAY, MAX_DELAY,
                          MAX_RETRY, MIN_PDF_BYTES, download, log, load_manifest)


def fetch_page(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "ignore")


def find_pdfs(page):
    pdfs = re.findall(r'https://harvardlawreview\.org/wp-content/uploads/[^"\'<> ]+?\.pdf', page)
    return [p for p in dict.fromkeys(pdfs) if "Factsheet" not in p]


def main():
    manifest = load_manifest()
    failed = [r for r in manifest.values() if r.get("status") == "error"]
    print(f"failed records: {len(failed)}", flush=True)
    fixed = still = 0
    for r in failed:
        url = r["url"]
        candidates = []
        # 1) 解码 HTML 实体
        dec = html.unescape(url)
        if dec != url:
            candidates.append(dec)
        # 2) 从文章页重新提取所有 PDF
        try:
            page = fetch_page(r["article_url"])
            candidates.extend(find_pdfs(page))
        except Exception as e:
            print(f"[page fetch fail] {r['article_url']}: {e}", flush=True)
        success = False
        for cand in dict.fromkeys(candidates):
            try:
                size, md5 = download(cand, os.path.join(TARGET_DIR, r["filename"]))
                rec = dict(r)
                rec.update(status="ok", size=size, md5=md5, fixed_url=cand, attempts=1)
                log(rec)
                print(f"[FIXED] {r['filename'][:45]} <- {cand[-50:]}", flush=True)
                fixed += 1
                success = True
                break
            except Exception as e:
                print(f"  try {cand[-45:]}: {str(e)[:70]}", flush=True)
        if not success:
            still += 1
            print(f"[UNRESOLVED] {r['filename'][:50]} :: {url[-60:]}", flush=True)
        time.sleep(MIN_DELAY + random.random() * (MAX_DELAY - MIN_DELAY))
    print(f"DONE fixed={fixed} unresolved={still}", flush=True)


if __name__ == "__main__":
    main()
