"""Safe text extraction and duplicate detection for uploaded contract documents."""
from __future__ import annotations
import hashlib
import io
from pathlib import Path
from typing import Any

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_SUFFIXES = {".pdf", ".txt"}

class DocumentUploadError(ValueError):
    pass

def extract_uploaded_document(filename: str, content: bytes) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DocumentUploadError("Unsupported file type. Upload a PDF or TXT contract.")
    if not content:
        raise DocumentUploadError("The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise DocumentUploadError("File exceeds the 15 MB upload limit.")
    pages = None
    if suffix == ".txt":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = content.decode("cp1252")
            except UnicodeDecodeError as exc:
                raise DocumentUploadError("TXT encoding could not be read. Save it as UTF-8 and retry.") from exc
    else:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content), strict=False)
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception as exc:
                    raise DocumentUploadError("This PDF is encrypted. Upload an unlocked copy.") from exc
            pages_text = [(page.extract_text() or "") for page in reader.pages]
            pages = len(pages_text)
            text = "\n\n".join(f"[PDF page {i + 1}]\n{value}" for i, value in enumerate(pages_text) if value.strip())
        except DocumentUploadError:
            raise
        except Exception as exc:
            raise DocumentUploadError(f"PDF could not be parsed: {exc.__class__.__name__}") from exc
        if not text.strip():
            raise DocumentUploadError("No selectable text was found in this PDF. It may be scanned; run OCR first or upload the matching TXT copy.")
    text = text.replace("\x00", "").strip()
    if not text:
        raise DocumentUploadError("No readable text was found in the uploaded document.")
    return {"filename": Path(filename).name, "format": suffix[1:].upper(), "text": text, "characters": len(text), "pages": pages, "sha256": hashlib.sha256(content).hexdigest()}
