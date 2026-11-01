# ADR 0003 — pgvector inside PostgreSQL, a provider-agnostic AI adapter, and an offline-first default

**Status:** accepted · **Date:** 2026-11-01

## Context

Policy answers need vector retrieval. The app must run on a laptop without API keys, but should
be able to use a hosted LLM (Anthropic, OpenAI or any OpenAI-compatible server) when configured.

## Options considered

* **Separate vector database** (Pinecone, Qdrant, Chroma): another service to run, back up and
  keep consistent with document versions.
* **pgvector in the existing PostgreSQL (chosen):** chunks live next to `policy_documents`, so
  "only active versions" is a plain `JOIN ... WHERE status = 'active'`, inside the same transactions.
* **Vendor SDKs / an orchestration framework** vs **a small httpx adapter (chosen):** one
  `complete_json()` function with three providers, schema-shaped JSON output, injectable transport
  for tests, and no framework hiding the prompts.
* **Embeddings:** hosted API, local sentence-transformers, or a built-in hashing embedder.

## Decision

* pgvector with an HNSW cosine index on `vector(384)`. All embedders produce 384 dimensions.
* Default `EMBEDDING_PROVIDER=hashing`: deterministic, dependency-free *lexical* vectors so RAG
  works offline with no download. `local` (one-time ~90 MB model download) and `openai` are
  optional and documented.
* Default `LLM_PROVIDER=none`: rules-based extraction and retrieval-only excerpts, each labelled.
  With an LLM configured, every output is validated server-side (evidence must appear in the
  user's text; citations must refer to retrieved active chunks) and falls back, labelled, on failure.

## Consequences

* One database to operate; versioning and retrieval stay consistent.
* The hashing embedder matches words, not meaning ("geyser" ≠ "water heater"). Measured recall@4
  is 0.96 on the labelled questions, but unsupported questions that share words with policies can
  slip past the similarity threshold (see the "salary" failure in the evaluation report).
* Changing the embedding provider requires re-ingesting documents (chunks record their
  `embedding_model`, and retrieval only reads chunks from the current model) and re-tuning
  `RAG_MIN_SIMILARITY`.
* The hosted-LLM code paths are unit-tested against recorded-shape mock responses; they were not
  exercised against a live provider in the reference run (no key was available).
