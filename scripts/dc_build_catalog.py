#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把 dc_data/jsonl/*.jsonl 汇总成 Excel + CSV 目录
=================================================
输出：
  Digital_Commons_法律期刊目录.xlsx   总览 + 全部文献 + 每刊一表
  Digital_Commons_法律期刊目录.csv    全量明细（UTF-8-SIG，Excel 直接双击可读）
"""
import glob
import json
import os
import re
from collections import Counter, defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

OUT_DIR = "dc_data"
JSONL_DIR = os.path.join(OUT_DIR, "jsonl")

COLS = ["期刊", "年份", "卷", "期", "起始页", "标题", "作者", "类型", "PDF直链", "文章页"]
KEYS = ["journal", "year", "volume", "issue", "start_page", "title", "authors",
        "doc_type", "pdf_url", "coverpage_url"]
WIDTH = [26, 7, 6, 6, 8, 78, 34, 11, 62, 58]


def load():
    rows = []
    for p in sorted(glob.glob(os.path.join(JSONL_DIR, "*.jsonl"))):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    # 去重：同一 oai_id + title
    seen, uniq = set(), []
    for r in rows:
        k = (r.get("oai_id"), r.get("title"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return rows, uniq


def sheet_name(base, used):
    b = re.sub(r"[\[\]:*?/\\]", "_", base)[:31]
    n, i = b, 1
    while n in used:
        suf = f"~{i}"
        n = b[:31 - len(suf)] + suf
        i += 1
    used.add(n)
    return n


def write_sheet(ws, header, data, widths, freeze="A2"):
    ws.append(header)
    hf = Font(bold=True, color="FFFFFF")
    hfill = PatternFill("solid", fgColor="2F5597")
    for c in range(1, len(header) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = hf
        cell.fill = hfill
        cell.alignment = Alignment(vertical="center", horizontal="center")
    for r in data:
        ws.append(r)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = freeze
    ws.auto_filter.ref = f"A1:{get_column_letter(len(header))}{max(len(data) + 1, 2)}"


def main():
    raw, rows = load()
    print(f"原始 {len(raw):,} 条，去重后 {len(rows):,} 条")

    wb = Workbook()
    ws = wb.active
    ws.title = "总览"

    by_j = defaultdict(list)
    for r in rows:
        by_j[r.get("journal") or r.get("source")].append(r)

    ov = []
    for j, rs in sorted(by_j.items(), key=lambda x: -len(x[1])):
        years = sorted({int(r["year"]) for r in rs
                        if r.get("year") and str(r["year"]).isdigit() and 1800 <= int(r["year"]) <= 2030})
        # 只认 1–3 位且合理的卷号，排除 WUSTL 那类拿年份充当卷号的脏值
        vols = sorted({int(r["volume"]) for r in rs
                       if r.get("volume") and str(r["volume"]).isdigit() and 1 <= int(r["volume"]) <= 999})
        ov.append([j, rs[0].get("host", ""), rs[0].get("source", ""), len(rs),
                   years[0] if years else "", years[-1] if years else "",
                   len(vols), f"第 {vols[0]}–{vols[-1]} 卷" if vols else ""])
    write_sheet(ws, ["期刊", "仓储域名", "代码", "文献数", "最早年", "最晚年", "卷数", "卷范围"],
                ov, [26, 34, 22, 9, 8, 8, 7, 16])
    ws.append([])
    ws.append(["合计", "", "", len(rows), "", "", "", ""])
    for c in range(1, 9):
        ws.cell(row=ws.max_row, column=c).font = Font(bold=True)

    # 全部文献
    ws_all = wb.create_sheet("全部文献")
    write_sheet(ws_all, COLS, [[r.get(k, "") for k in KEYS] for r in rows], WIDTH)

    # 每刊一表
    used = {"总览", "全部文献"}
    for j, rs in sorted(by_j.items(), key=lambda x: str(x[0])):
        name = sheet_name(str(j), used)
        w = wb.create_sheet(name)
        rs2 = sorted(rs, key=lambda r: (r.get("year") or "", int(r["volume"]) if r.get("volume", "").isdigit() else 0,
                                        int(r["issue"]) if r.get("issue", "").isdigit() else 0))
        write_sheet(w, COLS[1:], [[r.get(k, "") for k in KEYS[1:]] for r in rs2], WIDTH[1:])

    xlsx = os.path.join(OUT_DIR, "Digital_Commons_法律期刊目录.xlsx")
    wb.save(xlsx)
    print("已写", xlsx, os.path.getsize(xlsx) // 1024, "KB")

    csv = os.path.join(OUT_DIR, "Digital_Commons_法律期刊目录.csv")
    import csv as _csv
    with open(csv, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        w.writerow(COLS)
        for r in rows:
            w.writerow([r.get(k, "") for k in KEYS])
    print("已写", csv, os.path.getsize(csv) // 1024, "KB")

    # 统计
    print("\n=== 年度分布（近 30 年）===")
    yc = Counter(r["year"] for r in rows if r.get("year"))
    for y in sorted(yc)[-30:]:
        print(f"  {y}  {yc[y]:>6,}")
    print("\n=== 类型分布 ===")
    for k, v in Counter(r.get("doc_type") for r in rows).most_common(12):
        print(f"  {v:>6,}  {k}")


if __name__ == "__main__":
    main()
