"""Turns Markdown into a Word, PDF, PowerPoint, Excel, CSV or Markdown file. Runs inside .venv-code:
    .venv-code/bin/python exportdoc.py FORMAT INPUT.md OUTPUT [TITLE]
Supported Markdown: headings, paragraphs, bold, italic, inline code, bullet and numbered lists, tables, code blocks, rules."""
import csv
import re
import sys
from pathlib import Path

FONTS = Path("/System/Library/Fonts/Supplemental")


def parse(md):
    """-> list of blocks: ('h', level, text) ('p', text) ('ul', [items]) ('ol', [items]) ('table', [[cells]]) ('code', text) ('hr',)"""
    lines, blocks, i = md.replace("\r\n", "\n").split("\n"), [], 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1; continue
        if ln.strip().startswith("```"):
            i += 1; buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            blocks.append(("code", "\n".join(buf))); i += 1; continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            blocks.append(("h", len(m.group(1)), m.group(2).strip())); i += 1; continue
        if re.match(r"^\s*([-*_])\1{2,}\s*$", ln):
            blocks.append(("hr",)); i += 1; continue
        if ln.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", lines[i]):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            blocks.append(("table", rows)); continue
        if re.match(r"^\s*[-*+]\s+", ln):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*+]\s+", "", lines[i])); i += 1
            blocks.append(("ul", items)); continue
        if re.match(r"^\s*\d+[.)]\s+", ln):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+[.)]\s+", "", lines[i])); i += 1
            blocks.append(("ol", items)); continue
        buf = [ln.strip()]; i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6}\s|\s*[-*+]\s|\s*\d+[.)]\s|```|\s*\|)", lines[i]):
            buf.append(lines[i].strip()); i += 1
        blocks.append(("p", " ".join(buf)))
    return blocks


def runs(text):
    """Inline markup -> [(text, bold, italic, code)]"""
    out = []
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|_[^_\s][^_]*_)", text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append((part[2:-2], True, False, False))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append((part[1:-1], False, False, True))
        elif len(part) > 2 and ((part[0] == "*" and part[-1] == "*") or (part[0] == "_" and part[-1] == "_")):
            out.append((part[1:-1], False, True, False))
        else:
            out.append((part, False, False, False))
    return out


def plain(text):
    return "".join(t for t, *_ in runs(text))


def to_docx(blocks, out, title):
    from docx import Document
    from docx.shared import Pt
    d = Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)

    def fill(par, text):
        for t, b, i, c in runs(text):
            r = par.add_run(t); r.bold = b; r.italic = i
            if c:
                r.font.name = "Courier New"
    for b in blocks:
        if b[0] == "h":
            d.add_heading(plain(b[2]), min(b[1], 4) - 1 if b[1] > 1 else 0 if not d.paragraphs else 1)
        elif b[0] == "p":
            fill(d.add_paragraph(), b[1])
        elif b[0] in ("ul", "ol"):
            for it in b[1]:
                fill(d.add_paragraph(style="List Bullet" if b[0] == "ul" else "List Number"), it)
        elif b[0] == "table":
            rows = b[1]; n = max(len(r) for r in rows)
            t = d.add_table(rows=len(rows), cols=n); t.style = "Light Grid Accent 1"
            for ri, r in enumerate(rows):
                for ci in range(n):
                    cell = t.cell(ri, ci); cell.text = ""
                    fill(cell.paragraphs[0], r[ci] if ci < len(r) else "")
                    if ri == 0:
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
            d.add_paragraph()
        elif b[0] == "code":
            p = d.add_paragraph(); r = p.add_run(b[1]); r.font.name = "Courier New"; r.font.size = Pt(9.5)
    d.save(out)


def to_pdf(blocks, out, title):
    from fpdf import FPDF
    pdf = FPDF(format="A4"); pdf.set_margins(20, 18, 20); pdf.set_auto_page_break(True, 18)
    pdf.add_font("A", "", str(FONTS / "Arial Unicode.ttf"))
    reg = "A"
    try:
        pdf.add_font("A", "B", str(FONTS / "Arial Bold.ttf")); pdf.add_font("A", "I", str(FONTS / "Arial Italic.ttf"))
        pdf.add_font("A", "BI", str(FONTS / "Arial Bold Italic.ttf")); pdf.add_font("M", "", str(FONTS / "Courier New.ttf"))
        mono = "M"
    except Exception:
        mono = "A"
    pdf.add_page()

    def write(text, size=11, h=6, indent=0):
        pdf.set_x(pdf.l_margin + indent)
        for t, b, i, c in runs(text):
            pdf.set_font(mono if c else reg, ("B" if b else "") + ("I" if i else "") if not c else "", size)
            pdf.write(h, t)
        pdf.ln(h)
    for b in blocks:
        if b[0] == "h":
            pdf.ln(3); size = {1: 20, 2: 16, 3: 13}.get(b[1], 12); pdf.set_font(reg, "B", size); pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, size * 0.55, plain(b[2]), new_x="LMARGIN", new_y="NEXT"); pdf.ln(1)
        elif b[0] == "p":
            write(b[1]); pdf.ln(2)
        elif b[0] in ("ul", "ol"):
            for n, it in enumerate(b[1], 1):
                pdf.set_font(reg, "", 11); pdf.set_x(pdf.l_margin + 4); pdf.write(6, ("•  " if b[0] == "ul" else f"{n}.  "))
                for t, bo, ita, c in runs(it):
                    pdf.set_font(mono if c else reg, ("B" if bo else "") + ("I" if ita else "") if not c else "", 11); pdf.write(6, t)
                pdf.ln(6)
            pdf.ln(2)
        elif b[0] == "table":
            rows = b[1]; n = max(len(r) for r in rows); w = (pdf.w - pdf.l_margin - pdf.r_margin) / n
            for ri, r in enumerate(rows):
                pdf.set_font(reg, "B" if ri == 0 else "", 10)
                if ri == 0:
                    pdf.set_fill_color(235, 235, 235)
                y0 = pdf.get_y(); cells = [plain(r[c]) if c < len(r) else "" for c in range(n)]
                lines = [pdf.multi_cell(w, 5.5, t, dry_run=True, output="LINES") for t in cells]; hmax = max(len(l) for l in lines) * 5.5 + 1
                if y0 + hmax > pdf.h - 18:
                    pdf.add_page(); y0 = pdf.get_y()
                for c, t in enumerate(cells):
                    pdf.set_xy(pdf.l_margin + c * w, y0)
                    pdf.multi_cell(w, 5.5, t, border=1, fill=(ri == 0), max_line_height=5.5)
                pdf.set_y(y0 + hmax)
            pdf.ln(3)
        elif b[0] == "code":
            pdf.set_font(mono, "", 9); pdf.set_fill_color(244, 244, 244); pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 4.8, b[1], fill=True, new_x="LMARGIN", new_y="NEXT"); pdf.ln(3)
        elif b[0] == "hr":
            y = pdf.get_y() + 2; pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y); pdf.ln(5)
    pdf.output(out)


def to_pptx(blocks, out, title):
    from pptx import Presentation
    from pptx.util import Pt
    pr = Presentation(); pr.slide_width, pr.slide_height = 12192000, 6858000
    slides, cur = [], None
    for b in blocks:
        if b[0] == "h" and b[1] <= 2:
            cur = {"title": plain(b[2]), "items": [], "table": None}; slides.append(cur)
        else:
            if cur is None:
                cur = {"title": title or "Presentation", "items": [], "table": None}; slides.append(cur)
            if b[0] == "h":
                cur["items"].append((0, plain(b[2]), True))
            elif b[0] == "p":
                cur["items"].append((0, plain(b[1]), False))
            elif b[0] in ("ul", "ol"):
                cur["items"] += [(1, plain(x), False) for x in b[1]]
            elif b[0] == "table":
                cur["table"] = b[1]
            elif b[0] == "code":
                cur["items"].append((0, b[1], False))
    if not slides:
        slides = [{"title": title or "Presentation", "items": [], "table": None}]
    for sl in slides:
        if sl["table"]:
            s = pr.slides.add_slide(pr.slide_layouts[5]); s.shapes.title.text = sl["title"]
            rows = sl["table"]; n = max(len(r) for r in rows)
            gt = s.shapes.add_table(len(rows), n, 600000, 1600000, 10992000, 400000 * len(rows)).table
            for ri, r in enumerate(rows):
                for ci in range(n):
                    gt.cell(ri, ci).text = plain(r[ci]) if ci < len(r) else ""
                    for p in gt.cell(ri, ci).text_frame.paragraphs:
                        for run in p.runs:
                            run.font.size = Pt(16)
        else:
            s = pr.slides.add_slide(pr.slide_layouts[1]); s.shapes.title.text = sl["title"]
            tf = s.placeholders[1].text_frame; tf.clear(); first = True
            for lvl, text, bold in sl["items"][:12]:
                p = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
                p.text = text; p.level = 0
                for run in p.runs:
                    run.font.size = Pt(22 if len(sl["items"]) < 7 else 18); run.font.bold = bold
    pr.save(out)


def to_xlsx(blocks, out, title):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    wb = Workbook(); wb.remove(wb.active)
    tables = [b[1] for b in blocks if b[0] == "table"]
    if not tables:   # no tables: one column of text
        tables = [[["Text"]] + [[plain(b[1] if b[0] == "p" else b[2])] for b in blocks if b[0] in ("p", "h")]]
    for n, rows in enumerate(tables, 1):
        ws = wb.create_sheet(f"Table {n}" if len(tables) > 1 else "Sheet1")
        for r in rows:
            vals = []
            for c in r:
                c = plain(c); cc = c.replace(",", "") if re.match(r"^-?[\d,]*\.?\d+$", c) else None
                vals.append((float(cc) if "." in cc else int(cc)) if cc else c)
            ws.append(vals)
        for c in ws[1]:
            c.font = Font(bold=True)
        for col in range(1, ws.max_column + 1):
            ws.column_dimensions[get_column_letter(col)].width = min(60, max(10, max(len(str(ws.cell(r, col).value or "")) for r in range(1, ws.max_row + 1)) + 2))
    wb.save(out)


def to_csv(blocks, out, title):
    tables = [b[1] for b in blocks if b[0] == "table"]
    rows = tables[0] if tables else [[plain(b[1])] for b in blocks if b[0] == "p"]
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows([[plain(c) for c in r] for r in rows])


def main(fmt, src, out, title=""):
    md = Path(src).read_text()
    if fmt in ("md", "txt"):
        Path(out).write_text(md); return
    {"docx": to_docx, "pdf": to_pdf, "pptx": to_pptx, "xlsx": to_xlsx, "csv": to_csv}[fmt](parse(md), out, title)


if __name__ == "__main__":
    main(*sys.argv[1:5])
