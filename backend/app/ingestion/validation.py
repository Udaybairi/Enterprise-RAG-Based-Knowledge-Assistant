"""Upload validation: extension allow-list, size limit and magic-byte sniffing."""
from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import PurePath

from app.config import get_settings
from app.core.exceptions import ValidationFailedError

_ZIP_MEMBERS = {".docx": "word/document.xml", ".xlsx": "xl/workbook.xml", ".pptx": "ppt/presentation.xml"}


def safe_filename(name: str) -> str:
    base = PurePath(name.replace("\\", "/")).name
    base = re.sub(r"[^\w.\- ()]", "_", base).strip(" .")
    return base[:200] or "document"


def validate_upload(filename: str, data: bytes) -> str:
    """Return the normalised extension or raise ``ValidationFailedError``."""
    settings = get_settings()
    ext = PurePath(filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise ValidationFailedError(f"File type '{ext or 'none'}' is not allowed")
    if not data:
        raise ValidationFailedError("File is empty")
    if len(data) > settings.max_upload_bytes:
        raise ValidationFailedError(f"File exceeds the {settings.max_upload_size_mb} MB limit")
    head = data[:8]
    if ext == ".pdf" and not data[:1024].lstrip().startswith(b"%PDF"):
        raise ValidationFailedError("File content is not a valid PDF")
    if ext in _ZIP_MEMBERS:
        if head[:2] != b"PK":
            raise ValidationFailedError(f"File content is not a valid {ext} (Office Open XML) file")
        try:
            with zipfile.ZipFile(BytesIO(data)) as zf:
                names = set(zf.namelist())
                total = sum(i.file_size for i in zf.infolist())
        except zipfile.BadZipFile as exc:
            raise ValidationFailedError(f"Corrupted {ext} archive") from exc
        if _ZIP_MEMBERS[ext] not in names:
            raise ValidationFailedError(f"File content does not match the {ext} format")
        if total > 50 * len(data) + 200 * 1024 * 1024:  # zip-bomb guard
            raise ValidationFailedError("Archive expands to a suspicious size")
    if ext in (".txt", ".md", ".markdown", ".csv"):
        if b"\x00" in data[:4096]:
            raise ValidationFailedError("Text file appears to be binary")
    return ext
