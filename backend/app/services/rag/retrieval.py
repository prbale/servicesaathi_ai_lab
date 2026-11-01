"""Top-k vector retrieval over ACTIVE, non-quarantined chunks with pgvector.

SQL shape (cosine distance operator `<=>`):

    SELECT ... , 1 - (embedding <=> :query_vector) AS similarity
    FROM document_chunks c JOIN policy_documents d ON d.id = c.document_id
    WHERE d.status = 'active' AND NOT c.is_quarantined AND c.embedding_model = :model
    ORDER BY embedding <=> :query_vector
    LIMIT :k
"""
from dataclasses import asdict, dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models import DocumentChunk, PolicyDocument
from ..llm.providers import get_embedder


@dataclass
class Passage:
    chunk_id: int
    document_id: int
    doc_key: str
    title: str
    version: int
    section: str
    content: str
    similarity: float

    def citation(self) -> dict:
        return {"chunk_id": self.chunk_id, "title": self.title, "version": self.version, "section": self.section,
                "doc_key": self.doc_key}

    def to_dict(self) -> dict:
        return asdict(self)


def retrieve(db: Session, question: str, k: int | None = None) -> tuple[list[Passage], dict]:
    k = k or get_settings().rag_top_k
    embedder = get_embedder()
    qvec = embedder.embed([question])[0]
    distance = DocumentChunk.embedding.cosine_distance(qvec)
    stmt = (
        select(DocumentChunk.id, DocumentChunk.document_id, PolicyDocument.doc_key, PolicyDocument.title,
               PolicyDocument.version, DocumentChunk.section_title, DocumentChunk.content,
               (1 - distance).label("similarity"))
        .join(PolicyDocument, PolicyDocument.id == DocumentChunk.document_id)
        .where(PolicyDocument.status == "active", DocumentChunk.is_quarantined.is_(False),
               DocumentChunk.embedding_model == embedder.name)
        .order_by(distance)
        .limit(k)
    )
    # Filtered HNSW scans can return fewer rows than LIMIT; widen the candidate list.
    db.execute(text("SET LOCAL hnsw.ef_search = 100"))
    rows = db.execute(stmt).all()
    passages = [Passage(r[0], r[1], r[2], r[3], r[4], r[5], r[6], round(float(r[7]), 4)) for r in rows]
    info = {"embedding_model": embedder.name, "k": k,
            "sql": "SELECT ... ORDER BY embedding <=> :query_vector LIMIT :k "
                   "(active versions only, quarantined chunks excluded)"}
    return passages, info
