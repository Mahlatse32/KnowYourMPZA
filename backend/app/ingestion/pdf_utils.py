import hashlib
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from pypdf import PdfReader

from app.ingestion.people_assembly import create_slug


def download_file(url: str) -> bytes:
    response = requests.get(url, timeout=30, headers={"User-Agent": "KnowYourMPZA/0.1"})
    response.raise_for_status()
    return response.content


def archive_pdf(source_name: str, url: str, content: bytes) -> str:
    source_slug = create_slug(source_name)
    primary_base = Path("data/raw/pdfs") / source_slug
    primary_path = _archive_path(url, primary_base, suffix=".pdf")
    primary_path.parent.mkdir(parents=True, exist_ok=True)
    primary_path.write_bytes(content)

    if source_slug in {"parliamentary-questions", "parliament-questions", "parliament_questions"}:
        question_path = _archive_path(url, Path("data/raw/parliament_questions"), suffix=".pdf")
        question_path.parent.mkdir(parents=True, exist_ok=True)
        question_path.write_bytes(content)
        return str(question_path)
    return str(primary_path)


def extract_pdf_text(file_path: str) -> str:
    try:
        reader = PdfReader(file_path)
        pages = [(page.extract_text() or "") for page in reader.pages]
        return " ".join(" ".join(pages).split())
    except Exception as exc:
        raise ValueError(f"PDF text extraction failed: {exc}") from exc


def is_pdf_url(url: str) -> bool:
    parsed = urlparse(url)
    return unquote(parsed.path).lower().endswith(".pdf")


def _archive_path(url: str, base_dir: Path, suffix: str) -> Path:
    parsed = urlparse(url)
    name = Path(unquote(parsed.path.rstrip("/"))).name or parsed.netloc or "document"
    stem = create_slug(Path(name).stem or name)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return base_dir / f"{stem}-{digest}{suffix}"
