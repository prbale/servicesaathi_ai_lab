"""Provider-agnostic adapters for the hosted LLM and for embeddings.

LLM_PROVIDER     = none | anthropic | openai | openai_compatible
EMBEDDING_PROVIDER = hashing | local | openai

Design rules
* Plain HTTPS calls through httpx — no vendor SDKs, no agent frameworks.
* The LLM only ever returns JSON matching a schema we supply; the server validates it.
* The LLM never sees credentials, never runs SQL and never creates bookings.
* Any failure raises LLMUnavailable so callers can fall back to a clearly labelled
  non-LLM path. A fallback is never presented as an LLM answer.
"""
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from functools import lru_cache

import httpx

from ...config import get_settings
from ...models import EMBEDDING_DIM

# Tests can inject an httpx.MockTransport here.
_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def _client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout, transport=_transport) if _transport else httpx.Client(timeout=timeout)


class LLMUnavailable(Exception):
    """Raised when no provider is configured or the provider call/parse failed."""


@dataclass
class LLMResult:
    data: dict
    provider: str
    model: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None

    def usage(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": estimate_cost(self.input_tokens, self.output_tokens),
        }


def estimate_cost(input_tokens: int | None, output_tokens: int | None) -> dict | None:
    """Only when prices are configured. Always labelled as an estimate."""
    s = get_settings()
    if s.llm_input_price_per_mtok is None or s.llm_output_price_per_mtok is None:
        return None
    if input_tokens is None or output_tokens is None:
        return None
    usd = input_tokens / 1e6 * s.llm_input_price_per_mtok + output_tokens / 1e6 * s.llm_output_price_per_mtok
    return {"value": round(usd, 6), "label": "ESTIMATE from configured per-token prices, not a bill"}


def complete_json(system: str, user: str, schema: dict, name: str) -> LLMResult:
    """Ask the configured LLM for a JSON object that matches `schema`."""
    s = get_settings()
    if not s.llm_enabled:
        raise LLMUnavailable("No hosted LLM configured (LLM_PROVIDER/LLM_MODEL/LLM_API_KEY).")
    start = time.perf_counter()
    try:
        if s.llm_provider == "anthropic":
            result = _anthropic(system, user, schema, name)
        elif s.llm_provider in ("openai", "openai_compatible"):
            result = _openai(system, user, schema, name)
        else:
            raise LLMUnavailable(f"Unknown LLM_PROVIDER '{s.llm_provider}'.")
    except LLMUnavailable:
        raise
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
        raise LLMUnavailable(f"LLM call failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return result


def _anthropic(system: str, user: str, schema: dict, name: str) -> LLMResult:
    s = get_settings()
    body = {
        "model": s.llm_model,
        "max_tokens": 1024,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        # Forcing a single tool call is how we get schema-shaped JSON back.
        "tools": [{"name": name, "description": f"Return the {name} result.", "input_schema": schema}],
        "tool_choice": {"type": "tool", "name": name},
    }
    with _client(s.llm_timeout_seconds) as c:
        r = c.post(
            (s.llm_base_url or "https://api.anthropic.com") + "/v1/messages",
            headers={"x-api-key": s.llm_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=body,
        )
    r.raise_for_status()
    payload = r.json()
    block = next(b for b in payload["content"] if b.get("type") == "tool_use")
    usage = payload.get("usage", {})
    return LLMResult(block["input"], "anthropic", s.llm_model, 0.0, usage.get("input_tokens"), usage.get("output_tokens"))


def _openai(system: str, user: str, schema: dict, name: str) -> LLMResult:
    s = get_settings()
    base = s.llm_base_url if s.llm_provider == "openai_compatible" else "https://api.openai.com/v1"
    body = {
        "model": s.llm_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
    }
    with _client(s.llm_timeout_seconds) as c:
        r = c.post(base.rstrip("/") + "/chat/completions",
                   headers={"Authorization": f"Bearer {s.llm_api_key}"}, json=body)
    r.raise_for_status()
    payload = r.json()
    content = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage", {})
    return LLMResult(json.loads(content), s.llm_provider, s.llm_model, 0.0,
                     usage.get("prompt_tokens"), usage.get("completion_tokens"))


# ===================================================================== embeddings

_STOP = set(
    "a an the and or but if of to in on at for with from by is are was were be been being do does did "
    "i me my we our you your it its this that these those what which who how when where can could would "
    "should will shall may might must have has had not no yes any all".split()
)


def _stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "ions", "ion", "edly", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


class HashingEmbedder:
    """Built-in, dependency-free *lexical* embedder (feature hashing).

    It hashes word stems, word bigrams and character 4-grams into 384 dimensions.
    It captures word overlap, NOT meaning: "geyser" and "water heater" look unrelated.
    It exists so RAG works offline; use EMBEDDING_PROVIDER=local or openai for semantics.
    """

    name = "hashing-v1-384"
    kind = "lexical (feature hashing) — no download, not semantic"

    def _features(self, text: str) -> dict[str, float]:
        words = [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP]
        feats: dict[str, float] = {}
        for w in words:
            feats["w:" + w] = feats.get("w:" + w, 0) + 1.0
            padded = f"#{w}#"
            for i in range(len(padded) - 3):
                g = "c:" + padded[i : i + 4]
                feats[g] = feats.get(g, 0) + 0.3
        for a, b in zip(words, words[1:]):
            feats[f"b:{a}_{b}"] = feats.get(f"b:{a}_{b}", 0) + 0.7
        return feats

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * EMBEDDING_DIM
            for f, weight in self._features(t).items():
                h = int(hashlib.md5(f.encode()).hexdigest(), 16)
                vec[h % EMBEDDING_DIM] += (1 if (h >> 64) & 1 else -1) * (1 + math.log(weight + 1))
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


class LocalSentenceTransformerEmbedder:
    """Semantic embeddings on your machine. Requires `pip install -r requirements-local-embeddings.txt`.
    The model (~90 MB) downloads ONCE from Hugging Face on first use, then is cached."""

    kind = "semantic (local sentence-transformers) — one-time model download"

    def __init__(self, model: str):
        self.model_name = model or "sentence-transformers/all-MiniLM-L6-v2"
        self.name = f"local:{self.model_name}"
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:
            raise LLMUnavailable("sentence-transformers is not installed") from exc
        self._model = SentenceTransformer(self.model_name)
        if self._model.get_sentence_embedding_dimension() != EMBEDDING_DIM:
            raise LLMUnavailable(f"Model must produce {EMBEDDING_DIM}-dim vectors.")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.encode(texts, normalize_embeddings=True)]


class OpenAIEmbedder:
    kind = "semantic (hosted embeddings API)"

    def __init__(self):
        s = get_settings()
        self.model_name = s.embedding_model or "text-embedding-3-small"
        self.name = f"openai:{self.model_name}:{EMBEDDING_DIM}"
        self.key = s.embedding_api_key or s.llm_api_key
        self.base = (s.embedding_base_url or "https://api.openai.com/v1").rstrip("/")
        if not self.key:
            raise LLMUnavailable("EMBEDDING_API_KEY is not set.")

    def embed(self, texts: list[str]) -> list[list[float]]:
        with _client(30) as c:
            r = c.post(self.base + "/embeddings", headers={"Authorization": f"Bearer {self.key}"},
                       json={"model": self.model_name, "input": texts, "dimensions": EMBEDDING_DIM})
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]


@lru_cache
def get_embedder():
    p = get_settings().embedding_provider
    if p == "local":
        return LocalSentenceTransformerEmbedder(get_settings().embedding_model)
    if p == "openai":
        return OpenAIEmbedder()
    return HashingEmbedder()


def embedding_info() -> dict:
    try:
        e = get_embedder()
        return {"provider": get_settings().embedding_provider, "model": e.name, "kind": e.kind}
    except Exception as exc:  # report, don't crash /meta
        return {"provider": get_settings().embedding_provider, "model": None, "error": str(exc)[:200]}
