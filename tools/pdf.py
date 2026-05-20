import io

try:
    from pypdf import PdfReader
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


def extract_pdf_text(data: bytes) -> str:
    if not _AVAILABLE:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception:
        return ""
