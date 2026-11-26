#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build classified Excel + Markdown catalog from harvested HLR records.

Input:  hlr_pdf_catalog.jsonl
Output: HLR_PDF_文献目录.xlsx  /  HLR_PDF_文献目录.md
"""
import sys, re, json, os
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

SRC = "hlr_pdf_catalog.jsonl"
XLSX = "HLR_PDF_文献目录.xlsx"
MD = "HLR_PDF_文献目录.md"

HDR_FILL = PatternFill("solid", fgColor="1F4E79")
HDR_FONT = Font(color="FFFFFF", bold=True)


def load():
    recs = []
    for line in open(SRC, encoding="utf-8"):
        try:
            recs.append(json.loads(line))
        except Exception:
            pass
    return recs


def vol_of(u):
    m = re.search(r"vol-(\d+)", u)
    return int(m.group(1)) if m else ""


def issue_of(cite, url):
    m = re.search(r"vol-(\d+)/", url)
    return f"Vol.{m.group(1)}" if m else ""


def rows_of(recs):
    rows = []
    for r in recs:
        urls = r.get("pdf_urls") or []
        if not urls:
            continue
        v = vol_of(r["article_url"])
        for i, pdf in enumerate(urls):
            rows.append({
                "出版物": r.get("kind", ""),
                "卷": v,
                "栏目": r.get("genre") or "未标注",
                "主题": r.get("topic") or "",
                "引文": r.get("cite") or "",
                "标题": r.get("title") or "",
                "作者": "; ".join(r.get("authors") or []),
                "PDF_URL": pdf,
                "文章页_URL": r["article_url"],
                "PDF序号": i + 1 if len(urls) > 1 else "",
            })
    rows.sort(key=lambda x: (-x["卷"] if isinstance(x["卷"], int) else 0, x["栏目"], x["标题"]))
    return rows


def write_sheet(wb, name, rows, cols):
    ws = wb.create_sheet(name)
    ws.append(cols)
    for c in range(1, len(cols) + 1):
        cell = ws.cell(1, c)
        cell.fill = HDR_FILL
        cell.font = HDR_FONT
        cell.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    widths = {"标题": 50, "作者": 32, "PDF_URL": 68, "文章页_URL": 62,
              "主题": 20, "栏目": 16, "引文": 22, "出版物": 10, "卷": 8, "PDF序号": 8}
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(c, 16)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(rows)+1}"
    return ws


def build_excel(rows, recs):
    wb = Workbook()
    wb.remove(wb.active)
    cols = ["出版物", "卷", "栏目", "主题", "引文", "标题", "作者", "PDF_URL", "文章页_URL", "PDF序号"]

    write_sheet(wb, "总表", rows, cols)
    for kind in ["Print", "Forum"]:
        sub = [r for r in rows if r["出版物"] == kind]
        if sub:
            write_sheet(wb, kind, sub, cols)

    # 按栏目分表（合并同名栏目）
    by_genre = defaultdict(list)
    for r in rows:
        by_genre[r["栏目"]].append(r)
    used_names = {"总表", "统计", "Print", "Forum"}
    for genre, sub in sorted(by_genre.items(), key=lambda kv: -len(kv[1])):
        name = re.sub(r"[\\/*?:\[\]]", "_", genre)
        base = f"栏目-{name}"[:31]
        sheet_name, seq = base, 1
        while sheet_name in used_names:
            suffix = f"~{seq}"
            sheet_name = base[:31 - len(suffix)] + suffix
            seq += 1
        used_names.add(sheet_name)
        write_sheet(wb, sheet_name, sub, cols)

    # 统计表
    ws = wb.create_sheet("统计")
    ws.append(["维度", "类别", "PDF链接数"])
    for c in range(1, 4):
        ws.cell(1, c).fill = HDR_FILL
        ws.cell(1, c).font = HDR_FONT
    for dim, key in [("出版物", "出版物"), ("栏目", "栏目"), ("卷", "卷")]:
        cnt = Counter(r[key] for r in rows)
        for k, n in sorted(cnt.items(), key=lambda kv: str(kv[0])):
            ws.append([dim, k, n])
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 40
    ws.column_dimensions["C"].width = 12
    wb.save(XLSX)


def build_markdown(rows, recs):
    out = []
    out.append("# Harvard Law Review PDF 文献目录\n")
    out.append(f"> 数据来源：harvardlawreview.org 官方 sitemap 全量枚举\n")
    out.append(f"> 文章页总数：{len(recs)}；含 PDF 链接的文章：{len(set(r['文章页_URL'] for r in rows))}；PDF 链接总数：{len(rows)}\n")
    ok = sum(1 for r in recs if r.get("status") == "ok")
    no = sum(1 for r in recs if r.get("status") == "no_pdf")
    err = sum(1 for r in recs if r.get("status") == "error")
    out.append(f"> 抓取状态：成功 {ok} / 无 PDF {no} / 失败 {err}\n")

    by_kind = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_kind[r["出版物"]][r["栏目"]].append(r)
    for kind in ["Print", "Forum"]:
        out.append(f"\n## {kind}\n")
        for genre, sub in sorted(by_kind[kind].items(), key=lambda kv: -len(kv[1])):
            out.append(f"\n### {genre}（{len(sub)} 篇）\n")
            out.append("| 卷 | 主题 | 标题 | 作者 | PDF 链接 |")
            out.append("|---|---|---|---|---|")
            for r in sub:
                t = r["标题"].replace("|", "\\|")
                a = r["作者"].replace("|", "\\|")
                out.append(f"| {r['卷']} | {r['主题']} | {t} | {a} | [PDF]({r['PDF_URL']}) |")
    open(MD, "w", encoding="utf-8").write("\n".join(out) + "\n")


def main():
    recs = load()
    rows = rows_of(recs)
    print(f"records={len(recs)} rows(pdf)={len(rows)}")
    print("status:", dict(Counter(r.get("status") for r in recs)))
    print("genre:", dict(Counter(r["栏目"] for r in rows).most_common()))
    build_excel(rows, recs)
    build_markdown(rows, recs)
    print(f"Wrote {XLSX} and {MD}")


if __name__ == "__main__":
    main()
