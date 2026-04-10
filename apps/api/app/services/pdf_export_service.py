from __future__ import annotations

from pathlib import Path

from fastapi.responses import FileResponse, PlainTextResponse

from app.core.config import settings
from app.models.file_record import FileRecord
from app.models.pdf_literature import PdfDocument


def _storage_path(file_record: FileRecord) -> Path:
    return Path(settings.upload_dir) / (file_record.storage_path or file_record.file_name)


def build_bib(doc: PdfDocument, file_record: FileRecord) -> str:
    cite_key = f"file{file_record.id}"
    year = doc.publication_year or ""
    title = doc.title or file_record.file_name
    journal = doc.journal or ""
    doi = doc.doi or ""
    return (
        f"@article{{{cite_key},\n"
        f"  title = {{{title}}},\n"
        f"  author = {{{_authors_line(doc)}}},\n"
        f"  journal = {{{journal}}},\n"
        f"  year = {{{year}}},\n"
        f"  doi = {{{doi}}}\n"
        f"}}\n"
    )


def build_ris(doc: PdfDocument, file_record: FileRecord) -> str:
    lines = ["TY  - JOUR"]
    lines.append(f"TI  - {doc.title or file_record.file_name}")
    for a in _authors(doc):
        lines.append(f"AU  - {a}")
    if doc.journal:
        lines.append(f"JO  - {doc.journal}")
    if doc.publication_year:
        lines.append(f"PY  - {doc.publication_year}")
    if doc.doi:
        lines.append(f"DO  - {doc.doi}")
    lines.append("ER  -")
    return "\n".join(lines) + "\n"


def _authors(doc: PdfDocument) -> list[str]:
    raw = doc.authors_json
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []


def _authors_line(doc: PdfDocument) -> str:
    return " and ".join(_authors(doc))


def build_download_response(
    *,
    file_record: FileRecord,
    include_original: bool = True,
) -> FileResponse:
    """返回已上传的 PDF 原件（全文翻译 /  zip 打包译文已移除）。"""
    original_path = _storage_path(file_record)
    return FileResponse(path=original_path, filename=file_record.file_name, media_type="application/pdf")


def bib_response(content: str, file_name: str) -> PlainTextResponse:
    return PlainTextResponse(
        content=content,
        media_type="application/x-bibtex",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


def ris_response(content: str, file_name: str) -> PlainTextResponse:
    return PlainTextResponse(
        content=content,
        media_type="application/x-research-info-systems",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )
