"""Parse a Markdown policy document and split it into section-aware chunks.

Format (see data/policies/*.md):

    ---
    doc_key: cancellation-rescheduling
    title: Cancellation and Rescheduling
    version: 2
    ---
    ## Section heading
    Paragraphs...

Each chunk keeps its document and section metadata so answers can cite
"title · version · section". Long sections are packed paragraph by paragraph.
Plain-text files without headings become a single "Document" section.
"""
import re
from dataclasses import dataclass

MAX_CHARS = 700

# Text that looks like instructions to an AI rather than policy content.
INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above|earlier) (instructions|rules|context)",
    r"disregard (the |all |any )?(above|previous|prior|system)",
    r"you are now\b", r"\bsystem prompt\b", r"\bnew instructions\b", r"\bdeveloper mode\b",
    r"(tell|inform) (the |all )?(user|customer)s? that", r"do not (cite|mention) (this|the source)",
    r"\bassistant\s*:", r"<\s*/?\s*(script|system|instructions?)\b", r"reveal (your|the) (prompt|instructions)",
]


@dataclass
class ParsedDoc:
    doc_key: str
    title: str
    version: int | None
    body: str


@dataclass
class Chunk:
    index: int
    section: str
    content: str
    quarantine_reason: str | None = None


class DocumentFormatError(ValueError):
    pass


def parse(text: str, fallback_key: str = "", fallback_title: str = "") -> ParsedDoc:
    meta: dict[str, str] = {}
    body = text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = text[m.end():]
    key = meta.get("doc_key") or fallback_key
    title = meta.get("title") or fallback_title
    if not key or not re.fullmatch(r"[a-z0-9_-]+", key):
        raise DocumentFormatError("doc_key missing or invalid (use lowercase letters, digits, - or _).")
    if not title:
        raise DocumentFormatError("title is missing.")
    version = int(meta["version"]) if meta.get("version", "").isdigit() else None
    if not body.strip():
        raise DocumentFormatError("document body is empty.")
    return ParsedDoc(key, title, version, body)


def detect_injection(text: str) -> str | None:
    low = text.lower()
    for p in INJECTION_PATTERNS:
        m = re.search(p, low)
        if m:
            return f"instruction-like text: '{m.group(0)}'"
    return None


def split(doc: ParsedDoc) -> list[Chunk]:
    sections: list[tuple[str, str]] = []
    current_title, buf = "Document", []
    for line in doc.body.splitlines():
        if line.startswith(">"):  # document-level notice (e.g. "DEMO POLICY"), shown in the UI, not chunked
            continue
        h = re.match(r"^#{1,3}\s+(.*)", line)
        if h:
            if "".join(buf).strip():
                sections.append((current_title, "\n".join(buf).strip()))
            current_title, buf = h.group(1).strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        sections.append((current_title, "\n".join(buf).strip()))

    chunks: list[Chunk] = []
    for title, text in sections:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        packed, cur = [], ""
        for p in paragraphs:
            if cur and len(cur) + len(p) + 2 > MAX_CHARS:
                packed.append(cur)
                cur = p
            else:
                cur = f"{cur}\n\n{p}" if cur else p
        if cur:
            packed.append(cur)
        for piece in packed:
            # Long single paragraphs are cut at sentence boundaries.
            while len(piece) > MAX_CHARS * 1.5:
                cut = piece.rfind(". ", 0, MAX_CHARS) + 1 or MAX_CHARS
                chunks.append(Chunk(len(chunks), title, piece[:cut].strip(), detect_injection(piece[:cut])))
                piece = piece[cut:].strip()
            chunks.append(Chunk(len(chunks), title, piece, detect_injection(piece)))
    return chunks


def embedding_text(doc_title: str, chunk: Chunk) -> str:
    """What we embed: the content plus its titles, which helps short questions match."""
    return f"{doc_title} — {chunk.section}\n{chunk.content}"
