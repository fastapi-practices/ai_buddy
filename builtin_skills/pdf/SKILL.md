---
name: "pdf"
description: "Use when tasks involve reading, creating, or reviewing PDF files, including Chinese text; generate with reportlab and check with pdfplumber, pypdf and pypdfium2 since pages cannot be viewed in this environment."
metadata:
  version: "1.0.0"
---


# PDF Skill

## Environment notes (AI Buddy sandbox)

- `SKILL_DIR` is this skill's folder in the sandbox: `/workspace/skills/pdf` after `install_skill`.
- `reportlab`, `pdfplumber`, `pypdf`, `pypdfium2` and `office_oxide` are preinstalled. The sandbox has no network by default, so do not install packages.
- You cannot view images here, so the final visual inspection of rendered pages is not possible. Use the text and geometry checks below and tell the user that the layout was not inspected visually.

## When to use
- Read or review PDF content.
- Create PDFs programmatically with reliable formatting.
- Validate the generated file before delivery.

## Workflow
1. Use `reportlab` to generate PDFs when creating new documents.
2. Use `pdfplumber` (or `pypdf`) for text extraction and checks; do not rely on text extraction for layout fidelity.
3. After each meaningful update, run the checks below and fix every finding.

## Chinese and other CJK text
Register a font that contains the glyphs, otherwise characters are drawn as empty boxes:
```python
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdfmetrics.registerFont(TTFont('CJK', '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc', subfontIndex=0))
```
Then use `fontName="CJK"` in every style that can contain such text, including table cells and headers.

## Checks before delivery
```python
import pdfplumber

with pdfplumber.open('outbound/report.pdf') as pdf:
    print('pages:', len(pdf.pages))
    for number, page in enumerate(pdf.pages, start=1):
        words = page.extract_words()
        outside = [w for w in words if w['x0'] < 0 or w['top'] < 0 or w['x1'] > page.width or w['bottom'] > page.height]
        print(number, 'words:', len(words), 'outside page:', len(outside))
```
- Every page must contain the expected text, and no word may fall outside the page.
- Extract the text of a Chinese page and confirm the characters appear; empty or garbled text means the font was not applied.
- To confirm that every page renders without errors: `pypdfium2.PdfDocument(path)[i].render(scale=1)`.

## Temp and output conventions
- Use `tmp/` for intermediate files and delete them when done.
- Write final files under `outbound/` and deliver them with `deliver_file`.
- Keep filenames stable and descriptive.

## Quality expectations
- Maintain polished design: consistent typography, spacing, margins, and section hierarchy.
- Avoid clipped text, overlapping elements, broken tables, and unreadable glyphs.
- Charts, tables, and images must be aligned and clearly labeled.
- Use ASCII hyphens only. Avoid U+2011 (non-breaking hyphen) and other Unicode dashes.
- Citations and references must be human-readable; never leave tool tokens or placeholder strings.

## Final checks
- Do not deliver until the text and geometry checks pass.
- Confirm headers, footers and page numbering through text extraction.
- Keep intermediate files organized or remove them after final approval.
