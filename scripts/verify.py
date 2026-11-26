#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify download completeness: PDF magic, size, .part residue, filename collisions.

Usage:
    python verify.py <target_folder> <manifest.jsonl>

Checks:
  1. Every file starts with %PDF- and exceeds minimum size
  2. No .part temp files remain
  3. No filename collisions (one filename mapped from multiple URLs) —
     a silent overwrite bug when titles are truncated to fixed length
  4. URLs marked ok in manifest but with no file on disk
"""
import sys, os, glob, json, re
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
MIN_BYTES = 1000


def main():
    folder, manifest = sys.argv[1], sys.argv[2]
    files = glob.glob(os.path.join(folder, "*.pdf"))
    print(f"files: {len(files)}")

    bad = []
    sizes = []
    for f in files:
        sz = os.path.getsize(f)
        sizes.append(sz)
        with open(f, "rb") as h:
            if h.read(5) != b"%PDF-" or sz < MIN_BYTES:
                bad.append(os.path.basename(f))
    print(f"invalid_pdf: {len(bad)}")
    for b in bad[:10]:
        print("  ", b)

    parts = glob.glob(os.path.join(folder, "*.part"))
    print(f"part_files: {len(parts)}")

    recs = [json.loads(l) for l in open(manifest, encoding="utf-8")]
    # 每个 URL 取最后一条记录作为最终状态
    latest = {}
    for r in recs:
        latest[r["url"]] = r
    ok = [r for r in latest.values() if r["status"] == "ok"]
    err = [r for r in latest.values() if r["status"] != "ok"]
    print(f"manifest: urls={len(latest)} ok={len(ok)} error={len(err)}")

    actual = {os.path.basename(f) for f in files}
    fnmap = defaultdict(list)
    for r in ok:
        if r.get("filename"):
            fnmap[r["filename"]].append(r["url"])
    collisions = {fn: us for fn, us in fnmap.items() if len(us) > 1}
    print(f"filename_collisions: {len(collisions)}")
    for fn, us in collisions.items():
        print("  ", fn[:60], "->", len(us), "URLs (silent overwrite!)")

    missing = [r for r in ok if r.get("filename") and r["filename"] not in actual]
    print(f"ok_but_missing_on_disk: {len(missing)}")
    for r in missing[:10]:
        print("  ", r["filename"][:60], "::", r["url"][-45:])

    if sizes:
        print(f"size: total={sum(sizes)/1e6:.1f}MB min={min(sizes)/1e3:.0f}KB max={max(sizes)/1e6:.1f}MB")


if __name__ == "__main__":
    main()
