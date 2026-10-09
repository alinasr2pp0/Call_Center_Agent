"""Knowledge-base document ingestion: parse PDF/DOCX/TXT, chunk text, manage Document & KBArticle records."""
from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import zipfile
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Document, KBArticle, KBEmbedding
from app.rag import text as rag_text

MAX_UPLOAD_BYTES = 10 * 1024 * 1024       # 10 MB upload limit
MAX_UNZIPPED_BYTES = 50 * 1024 * 1024     # 50 MB zip decompression bomb safeguard
MAX_WORDS = 80
OVERLAP_MAX_WORDS = 20

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}


class DocumentError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _file_info(filename: str) -> Tuple[str, str]:
    if not filename or "." not in filename:
        raise DocumentError(415, "Unsupported file format (missing extension)")
    raw_name, ext = filename.rsplit(".", 1)
    ext = ext.lower().strip()
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentError(415, f"Unsupported file extension: .{ext}")
    # clean filename to title
    title = raw_name.replace("\\", "/").rsplit("/", 1)[-1]
    title = re.sub(r"[_]+", " ", title).strip()
    title = re.sub(r"\s+", " ", title)
    return title or "Document", ext


def _reflow(text: str) -> str:
    """Rejoin hyphenated words split across lines."""
    text = re.sub(r"(\w+)-\n(\w+)", r"\1\2", text)
    return text


def clean_text(text: str) -> str:
    """Normalize unicode, fold Arabic presentation forms, clean invisibles."""
    if not text:
        return ""
    # NFKC normalisation converts presentation forms (e.g. \ufefb -> لا)
    text = unicodedata.normalize("NFKC", text)
    # remove zero-width / control / directional marks
    text = re.sub(r"[\u200b\u200c\u200d\u200e\u200f\ufeff]", "", text)
    # unify newlines
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # clean spaces per line
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    # drop empty lines compaction
    result = []
    for line in lines:
        if line:
            result.append(line)
        elif result and result[-1] != "":
            result.append("")
    return "\n".join(result).strip()


def extract_text(data: bytes, file_type: str) -> str:
    if not data:
        raise DocumentError(422, "Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError(413, "Uploaded file exceeds size limit.")

    file_type = file_type.lower()
    if file_type == "txt":
        # check for null bytes
        if b"\x00" in data:
            raise DocumentError(422, "Binary file cannot be processed as text.")
        decoded = None
        for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1256", "latin-1"):
            try:
                decoded = data.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if decoded is None:
            raise DocumentError(422, "Could not decode text file encoding.")
        return clean_text(decoded)

    elif file_type == "docx":
        try:
            from docx import Document as DocxDocument
        except ImportError:
            raise DocumentError(422, "python-docx package is required to process DOCX files.")
        # check zip bomb
        buf = io.BytesIO(data)
        try:
            with zipfile.ZipFile(buf, "r") as zf:
                total_uncompressed = sum(info.file_size for info in zf.infolist())
                if total_uncompressed > MAX_UNZIPPED_BYTES:
                    raise DocumentError(413, "DOCX file exceeds decompressed size limit.")
        except DocumentError:
            raise
        except Exception:
            raise DocumentError(422, "Corrupted or invalid DOCX file.")

        buf.seek(0)
        try:
            doc = DocxDocument(buf)
            lines = []
            for child in doc.element.body:
                tag = child.tag.split("}")[-1]
                if tag == "p":
                    p_text = child.text or ""
                    if p_text.strip():
                        lines.append(p_text.strip())
                elif tag == "tbl":
                    for row in child.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr"):
                        cells = []
                        for cell in row.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc"):
                            cell_text = "".join(cell.itertext()).strip()
                            cells.append(cell_text)
                        if any(cells):
                            lines.append(" | ".join(cells))
            raw = "\n".join(lines)
            return clean_text(raw)
        except Exception as exc:
            if isinstance(exc, DocumentError):
                raise
            raise DocumentError(422, f"Failed to extract DOCX text: {exc}")

    elif file_type == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise DocumentError(422, "pypdf package is required to process PDF files.")
        buf = io.BytesIO(data)
        try:
            reader = PdfReader(buf)
            if reader.is_encrypted:
                raise DocumentError(422, "Password-protected PDF files are not supported.")
            pages_text = []
            for page in reader.pages:
                t = page.extract_text() or ""
                if t.strip():
                    pages_text.append(t)
            if not pages_text:
                raise DocumentError(422, "No readable text found in PDF (scanned or image-only).")
            raw = "\n".join(pages_text)
            raw = _reflow(raw)
            return clean_text(raw)
        except Exception as exc:
            if isinstance(exc, DocumentError):
                raise
            raise DocumentError(422, f"Failed to parse PDF: {exc}")

    else:
        raise DocumentError(415, f"Unsupported file type: {file_type}")


def _is_junk(text: str) -> bool:
    cleaned = text.strip()
    if len(cleaned) < 4:
        return True
    if re.match(r"^[-–—\s\d]+$", cleaned):
        return True
    if re.match(r"^Page\s+\d+\s+(?:of|/)\s+\d+$", cleaned, re.IGNORECASE):
        return True
    # check searchable tokens
    tokens = rag_text.tokenize(cleaned)
    if not tokens:
        return True
    return False


def chunk_text(text: str) -> List[str]:
    if not text:
        return []
    cleaned = clean_text(text)
    if not cleaned:
        return []

    # split into sentences
    raw_sentences = re.split(r"(?<=[.!?؟\n])\s+", cleaned)
    sentences = [s.strip() for s in raw_sentences if s.strip() and not _is_junk(s)]
    if not sentences:
        return []

    # build chunks with overlap
    chunks: List[str] = []
    current_sentences: List[str] = []
    current_word_count = 0

    for s in sentences:
        s_words = s.split()
        s_word_len = len(s_words)
        if s_word_len > MAX_WORDS:
            # sentence itself is huge, slice it
            for i in range(0, s_word_len, MAX_WORDS):
                sub_s = " ".join(s_words[i:i + MAX_WORDS])
                if current_sentences:
                    chunks.append(" ".join(current_sentences))
                    current_sentences = []
                    current_word_count = 0
                chunks.append(sub_s)
            continue

        if current_word_count + s_word_len > MAX_WORDS and current_sentences:
            chunks.append(" ".join(current_sentences))
            # keep overlap sentence if possible
            overlap = [current_sentences[-1]] if current_sentences else []
            current_sentences = overlap + [s]
            current_word_count = sum(len(x.split()) for x in current_sentences)
        else:
            current_sentences.append(s)
            current_word_count += s_word_len

    if current_sentences:
        chunks.append(" ".join(current_sentences))

    # deduplicate adjacent identical chunks
    deduped: List[str] = []
    for c in chunks:
        c = c.strip()
        if not c or _is_junk(c):
            continue
        if deduped and deduped[-1] == c:
            continue
        deduped.append(c)

    return deduped


def ingest(db: Session, filename: str, data: bytes, product: Optional[str], username: str) -> Document:
    title, file_type = _file_info(filename)
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError(413, "Uploaded file exceeds the 10 MB limit.")

    content_hash = hashlib.sha256(data).hexdigest()
    existing = db.query(Document).filter(Document.content_hash == content_hash).first()
    if existing:
        raise DocumentError(409, f"A document with identical content already exists ('{existing.title}').")

    extracted = extract_text(data, file_type)
    if not extracted or len(extracted.strip()) < 10:
        raise DocumentError(422, "No readable text could be extracted from the file.")

    chunks = chunk_text(extracted)
    if not chunks:
        raise DocumentError(422, "File contains no searchable knowledge content.")

    doc = Document(
        title=title,
        filename=filename,
        file_type=file_type,
        size_bytes=len(data),
        content_hash=content_hash,
        chunk_count=len(chunks),
        product=product or "عام",
        uploaded_by=username,
    )
    db.add(doc)
    db.flush()

    for idx, chunk in enumerate(chunks, start=1):
        subj = f"{title} (جزء {idx})" if len(chunks) > 1 else title
        article = KBArticle(
            document_id=doc.id,
            product=product or "عام",
            ticket_type="مستندات",
            subject=subj,
            description=f"مستند: {title}",
            resolution=chunk,
            status="published",
            priority="normal",
            channel="document",
        )
        db.add(article)

    db.commit()
    db.refresh(doc)
    return doc


def delete_document(db: Session, document: Document) -> None:
    doc_id = document.id
    # delete embeddings for associated articles
    article_ids = [a.id for a in db.query(KBArticle.id).filter(KBArticle.document_id == doc_id).all()]
    if article_ids:
        db.query(KBEmbedding).filter(KBEmbedding.article_id.in_(article_ids)).delete(synchronize_session=False)
        db.query(KBArticle).filter(KBArticle.document_id == doc_id).delete(synchronize_session=False)
    db.delete(document)
    db.commit()
