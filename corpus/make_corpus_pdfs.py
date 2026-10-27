"""Render every corpus .txt next to it as a one-page PDF, the format LLASER's loaders accept.

The .txt files stay the readable source; rerun this after editing one. Deterministic (no
timestamps, no random ids): rerunning reproduces the committed PDFs byte for byte. Needs PyMuPDF,
which the LLASER backend image has:

    docker run --rm --network none --user "$(id -u):$(id -g)" -v "$PWD/corpus:/corpus" \
      --entrypoint /usr/bin/python3.11 ghcr.io/pxl-research/llaser-workshop-demo/backend:1 \
      /corpus/make_corpus_pdfs.py

Run it from the repo root.
"""
from pathlib import Path

import pymupdf

PAGE_WIDTH, PAGE_HEIGHT, MARGIN = 595, 842, 54


def render(source: Path) -> Path:
    output = source.with_suffix(".pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    rect = pymupdf.Rect(MARGIN, MARGIN, PAGE_WIDTH - MARGIN, PAGE_HEIGHT - MARGIN)
    if page.insert_textbox(rect, source.read_text(encoding="utf-8"), fontsize=10, fontname="helv") < 0:
        raise RuntimeError(f"{source.name} does not fit on one page")
    doc.set_metadata({"title": source.stem})
    doc.save(output, garbage=4, deflate=True, no_new_id=True)
    doc.close()
    return output


if __name__ == "__main__":
    for txt in sorted(Path(__file__).parent.glob("*.txt")):
        print(f"wrote {render(txt)}")
