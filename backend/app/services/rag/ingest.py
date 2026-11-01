"""Document upload, versioning and ingestion (chunk → embed → store in pgvector).

Lifecycle of a policy_documents row:
    upload  → status=draft,  ingestion_status=pending
    ingest  → ingestion_status=running → succeeded: this version becomes ACTIVE and the
              previous active version becomes SUPERSEDED (one transaction)
            → failed: error recorded; the previous active version stays active
Retrieval only ever reads chunks of ACTIVE versions.
"""
import hashlib
from pathlib import Path

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from ... import time_utils as tu
from ...config import BACKEND_DIR
from ...db import session_scope
from ...models import DocumentChunk, PolicyDocument
from ..llm.providers import get_embedder
from . import chunking

POLICY_DIR = BACKEND_DIR / "data" / "policies"


def upload(db: Session, content: str, filename: str = "", uploaded_by: int | None = None,
           fallback_key: str = "", fallback_title: str = "") -> PolicyDocument:
    if len(content) > 200_000:
        raise chunking.DocumentFormatError("document is larger than 200 KB.")
    parsed = chunking.parse(content, fallback_key, fallback_title)
    latest = db.scalar(select(func.max(PolicyDocument.version)).where(PolicyDocument.doc_key == parsed.doc_key)) or 0
    version = parsed.version if parsed.version and parsed.version > latest else latest + 1
    doc = PolicyDocument(doc_key=parsed.doc_key, title=parsed.title, version=version, status="draft",
                         content=content, content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                         source_filename=filename, uploaded_by=uploaded_by, ingestion_status="pending")
    db.add(doc)
    db.flush()
    return doc


def ingest(document_id: int) -> dict:
    """Ingest one uploaded version. Safe to call again on a failed version."""
    with session_scope() as db:
        doc = db.get(PolicyDocument, document_id)
        if doc is None:
            raise ValueError("document not found")
        doc.ingestion_status, doc.ingestion_error = "running", None
    try:
        with session_scope() as db:
            doc = db.get(PolicyDocument, document_id)
            parsed = chunking.parse(doc.content, doc.doc_key, doc.title)
            chunks = chunking.split(parsed)
            embedder = get_embedder()
            vectors = embedder.embed([chunking.embedding_text(doc.title, c) for c in chunks])
            db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
            for c, v in zip(chunks, vectors):
                db.add(DocumentChunk(document_id=doc.id, chunk_index=c.index, section_title=c.section,
                                     content=c.content, embedding=v, embedding_model=embedder.name,
                                     is_quarantined=c.quarantine_reason is not None,
                                     quarantine_reason=c.quarantine_reason))
            # Activate this version and supersede the old one, atomically.
            db.execute(update(PolicyDocument)
                       .where(PolicyDocument.doc_key == doc.doc_key, PolicyDocument.status == "active",
                              PolicyDocument.id != doc.id)
                       .values(status="superseded"))
            db.flush()
            doc.status = "active"
            doc.ingestion_status = "succeeded"
            doc.chunk_count = len(chunks)
            doc.embedding_model = embedder.name
            doc.ingested_at = tu.now()
            quarantined = sum(c.quarantine_reason is not None for c in chunks)
        return {"document_id": document_id, "status": "succeeded", "chunks": len(chunks),
                "quarantined_chunks": quarantined, "embedding_model": embedder.name}
    except Exception as exc:
        with session_scope() as db:
            doc = db.get(PolicyDocument, document_id)
            doc.ingestion_status, doc.ingestion_error = "failed", f"{type(exc).__name__}: {str(exc)[:300]}"
            if doc.status == "draft":
                doc.status = "failed"
        return {"document_id": document_id, "status": "failed", "error": str(exc)[:300]}


def reingest_active() -> list[dict]:
    """Re-embed every active version (needed after changing EMBEDDING_PROVIDER)."""
    with session_scope() as db:
        ids = list(db.scalars(select(PolicyDocument.id).where(PolicyDocument.status == "active")))
    return [ingest(i) for i in ids]


def seed_policy_documents() -> dict:
    """Load the demo policies. The superseded v1 is loaded first to demonstrate versioning."""
    with session_scope() as db:
        db.execute(text("TRUNCATE document_chunks, policy_documents RESTART IDENTITY CASCADE"))
    files = sorted((POLICY_DIR / "superseded").glob("*.md")) + sorted(POLICY_DIR.glob("*.md"))
    results = []
    for f in files:
        with session_scope() as db:
            doc_id = upload(db, f.read_text(), filename=f.name).id
        results.append(ingest(doc_id))
    ok = sum(r["status"] == "succeeded" for r in results)
    return {"documents_ingested": ok, "failed": len(results) - ok,
            "chunks": sum(r.get("chunks", 0) for r in results)}


def document_dict(d: PolicyDocument) -> dict:
    return {"id": d.id, "doc_key": d.doc_key, "title": d.title, "version": d.version, "status": d.status,
            "ingestion_status": d.ingestion_status, "ingestion_error": d.ingestion_error,
            "chunk_count": d.chunk_count, "embedding_model": d.embedding_model,
            "source_filename": d.source_filename,
            "ingested_at": tu.to_local(d.ingested_at).isoformat() if d.ingested_at else None,
            "created_at": tu.to_local(d.created_at).isoformat() if d.created_at else None}


def read_policy_file(name: str) -> str:
    return (POLICY_DIR / Path(name).name).read_text()
