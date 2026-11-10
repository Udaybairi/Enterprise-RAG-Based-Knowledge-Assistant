"""Format-specific document loaders.

LangChain community loaders are used where they preserve the information we
need (PyPDFLoader keeps per-page boundaries, CSVLoader keeps rows,
TextLoader handles encoding detection). For DOCX, PPTX and XLSX we read the
native structure directly (python-docx / python-pptx / openpyxl) because the
generic loaders discard headings, slide numbers and table layout, which are
required for structure-aware chunking and accurate citations. Generic
fall-backs (Docx2txtLoader, Unstructured when installed) are used if the
structured path fails.
"""
from __future__ import annotations

import re
import warnings
from collections.abc import Callable
from pathlib import Path

from app.core.exceptions import DocumentProcessingError
from app.core.logging import get_logger
from app.ingestion.types import Block, ExtractedDocument

log = get_logger(__name__)
warnings.filterwarnings("ignore", message=".*langchain-community.*")

ROWS_PER_BLOCK = 25


def _table_to_markdown(rows: list[list[str]]) -> str:
    rows = [[(c or "").replace("\n", " ").replace("|", "/").strip() for c in r] for r in rows if any(r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------- PDF
def load_pdf(path: Path) -> ExtractedDocument:
    from langchain_community.document_loaders import PyPDFLoader

    try:
        pages = PyPDFLoader(str(path), mode="page").load()
    except Exception as exc:  # noqa: BLE001
        raise DocumentProcessingError(f"Could not read PDF (corrupted or encrypted?): {exc}") from exc
    blocks = []
    meta = {}
    for d in pages:
        page_no = int(d.metadata.get("page", 0)) + 1
        meta.setdefault("title", d.metadata.get("title"))
        meta.setdefault("author", d.metadata.get("author"))
        if d.page_content.strip():
            blocks.append(Block(text=d.page_content, kind="page", page_number=page_no))
    page_count = int(pages[0].metadata.get("total_pages", len(pages))) if pages else 0
    return ExtractedDocument(blocks, page_count, {k: v for k, v in meta.items() if v}, paginated=True)


# --------------------------------------------------------------------------- DOCX
def load_docx(path: Path) -> ExtractedDocument:
    try:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        d = docx.Document(str(path))
        blocks: list[Block] = []
        for el in d.element.body.iterchildren():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "p":
                p = Paragraph(el, d)
                text = p.text.strip()
                if not text:
                    continue
                style = (p.style.name or "").lower() if p.style is not None else ""
                m = re.match(r"heading (\d)", style)
                if m or style == "title":
                    blocks.append(Block(text, "heading", heading_level=int(m.group(1)) if m else 1))
                elif "list" in style:
                    blocks.append(Block(f"- {text}", "list"))
                else:
                    blocks.append(Block(text, "paragraph"))
            elif tag == "tbl":
                t = Table(el, d)
                md = _table_to_markdown([[c.text for c in row.cells] for row in t.rows])
                if md:
                    blocks.append(Block(md, "table"))
        props = d.core_properties
        meta = {"title": props.title or None, "author": props.author or None}
        # DOCX has no fixed pagination: page numbers stay None rather than being guessed.
        return ExtractedDocument(blocks, 0, {k: v for k, v in meta.items() if v}, paginated=False)
    except DocumentProcessingError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("python-docx failed (%s); falling back to Docx2txtLoader", exc)
        from langchain_community.document_loaders import Docx2txtLoader

        try:
            docs = Docx2txtLoader(str(path)).load()
        except Exception as exc2:  # noqa: BLE001
            raise DocumentProcessingError(f"Could not read DOCX (corrupted?): {exc2}") from exc2
        return ExtractedDocument([Block(d.page_content) for d in docs], 0, paginated=False)


# ------------------------------------------------------------------- TXT / MD
def load_text(path: Path) -> ExtractedDocument:
    from langchain_community.document_loaders import TextLoader

    try:
        docs = TextLoader(str(path), autodetect_encoding=True).load()
    except Exception as exc:  # noqa: BLE001
        raise DocumentProcessingError(f"Could not decode text file: {exc}") from exc
    return ExtractedDocument([Block(d.page_content, "text") for d in docs], 0, paginated=False)


def load_markdown(path: Path) -> ExtractedDocument:
    ext = load_text(path)
    blocks: list[Block] = []
    in_code = False
    buf: list[str] = []

    def flush():
        if buf:
            txt = "\n".join(buf).strip()
            if txt:
                kind = "table" if txt.startswith("|") else ("list" if re.match(r"^\s*([-*+]|\d+\.)\s", txt) else "paragraph")
                blocks.append(Block(txt, kind))
            buf.clear()

    for line in ext.text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            buf.append(line)
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line) if not in_code else None
        if m:
            flush()
            blocks.append(Block(m.group(2).strip(), "heading", heading_level=len(m.group(1))))
        elif not line.strip() and not in_code:
            flush()
        else:
            buf.append(line)
    flush()
    return ExtractedDocument(blocks, 0, paginated=False)


# ----------------------------------------------------------------------------- CSV
def load_csv(path: Path) -> ExtractedDocument:
    from langchain_community.document_loaders import CSVLoader

    try:
        rows = CSVLoader(str(path), autodetect_encoding=True).load()
    except Exception as exc:  # noqa: BLE001
        raise DocumentProcessingError(f"Could not parse CSV: {exc}") from exc
    blocks = []
    # Group rows so each block is a meaningful, self-describing unit ("key: value" lines).
    for start in range(0, len(rows), ROWS_PER_BLOCK):
        group = rows[start:start + ROWS_PER_BLOCK]
        first = int(group[0].metadata.get("row", start)) + 1
        last = int(group[-1].metadata.get("row", start + len(group) - 1)) + 1
        text = "\n\n".join(f"Row {int(r.metadata.get('row', 0)) + 1}:\n{r.page_content}" for r in group)
        blocks.append(Block(text, "row", section=[f"Rows {first}-{last}"], meta={"row_start": first, "row_end": last}))
    return ExtractedDocument(blocks, 0, {"rows": len(rows)}, paginated=False)


# ---------------------------------------------------------------------------- XLSX
def load_xlsx(path: Path) -> ExtractedDocument:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise DocumentProcessingError(f"Could not open spreadsheet: {exc}") from exc
    blocks = []
    try:
        for ws in wb.worksheets:
            rows = [["" if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
            rows = [r for r in rows if any(c.strip() for c in r)]
            if not rows:
                continue
            header, body = rows[0], rows[1:] or []
            if not body:
                blocks.append(Block(_table_to_markdown([header]), "table", section=[f"Sheet: {ws.title}"]))
                continue
            for start in range(0, len(body), ROWS_PER_BLOCK):
                part = body[start:start + ROWS_PER_BLOCK]
                blocks.append(Block(
                    _table_to_markdown([header] + part), "table",
                    section=[f"Sheet: {ws.title}", f"Rows {start + 2}-{start + 1 + len(part)}"],
                    meta={"sheet": ws.title},
                ))
    finally:
        wb.close()
    return ExtractedDocument(blocks, 0, {"sheets": len(wb.sheetnames)}, paginated=False)


# ---------------------------------------------------------------------------- PPTX
def load_pptx(path: Path) -> ExtractedDocument:
    try:
        from pptx import Presentation

        prs = Presentation(str(path))
    except Exception as exc:  # noqa: BLE001
        return _unstructured_fallback(path, exc)
    blocks = []
    for idx, slide in enumerate(prs.slides, start=1):
        title = None
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            title = slide.shapes.title.text_frame.text.strip() or None
        section = [title] if title else [f"Slide {idx}"]
        if title:
            blocks.append(Block(title, "heading", page_number=idx, heading_level=1))
        for shape in slide.shapes:
            if shape == slide.shapes.title:
                continue
            if getattr(shape, "has_table", False) and shape.has_table:
                md = _table_to_markdown([[c.text for c in r.cells] for r in shape.table.rows])
                if md:
                    blocks.append(Block(md, "table", page_number=idx, section=list(section)))
            elif shape.has_text_frame:
                text = "\n".join(p.text for p in shape.text_frame.paragraphs if p.text.strip())
                if text.strip():
                    blocks.append(Block(text, "paragraph", page_number=idx, section=list(section)))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip() if slide.notes_slide.notes_text_frame else ""
            if notes:
                blocks.append(Block(f"Speaker notes: {notes}", "paragraph", page_number=idx, section=list(section)))
    return ExtractedDocument(blocks, len(prs.slides), paginated=True)


def _unstructured_fallback(path: Path, original: Exception) -> ExtractedDocument:
    try:
        from langchain_community.document_loaders import UnstructuredFileLoader  # requires `unstructured`

        docs = UnstructuredFileLoader(str(path), mode="elements").load()
    except Exception as exc:  # noqa: BLE001
        raise DocumentProcessingError(f"Could not read file: {original}") from exc
    blocks = [Block(d.page_content, "paragraph", page_number=d.metadata.get("page_number")) for d in docs]
    return ExtractedDocument(blocks, max((b.page_number or 0) for b in blocks) if blocks else 0)


LOADERS: dict[str, Callable[[Path], ExtractedDocument]] = {
    ".pdf": load_pdf,
    ".docx": load_docx,
    ".txt": load_text,
    ".md": load_markdown,
    ".markdown": load_markdown,
    ".csv": load_csv,
    ".xlsx": load_xlsx,
    ".pptx": load_pptx,
}

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def load_document(path: Path, extension: str | None = None) -> ExtractedDocument:
    ext = (extension or path.suffix).lower()
    loader = LOADERS.get(ext)
    if loader is None:
        raise DocumentProcessingError(f"Unsupported file type: {ext}")
    return loader(path)
