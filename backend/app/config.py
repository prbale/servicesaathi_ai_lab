"""Application settings, read from environment variables (see .env.example).

Every value has a safe local default so the app runs without any hosted AI key.
Secrets (API keys, the token signing secret) are only ever read on the server.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # --- Core -----------------------------------------------------------
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/servicesaathi"
    app_secret: str = "change-me-local-demo-secret"  # signs login tokens
    display_timezone: str = "Asia/Kolkata"
    token_ttl_minutes: int = 12 * 60
    frontend_dist: str = str(BACKEND_DIR.parent / "frontend" / "dist")

    # --- ML artefacts ----------------------------------------------------
    model_dir: str = str(BACKEND_DIR / "artifacts")

    # --- Hosted LLM (optional) --------------------------------------------
    # none | anthropic | openai | openai_compatible
    llm_provider: str = "none"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""  # only for openai_compatible
    llm_timeout_seconds: float = 30.0
    # Optional pricing, USD per million tokens. Used only for a clearly labelled estimate.
    llm_input_price_per_mtok: float | None = None
    llm_output_price_per_mtok: float | None = None

    # --- Embeddings ------------------------------------------------------
    # hashing (built-in, no download) | local (sentence-transformers, one-time download) | openai
    embedding_provider: str = "hashing"
    embedding_model: str = ""
    embedding_api_key: str = ""
    embedding_base_url: str = ""

    # --- RAG -------------------------------------------------------------
    rag_top_k: int = 4
    # Below this cosine similarity the system abstains. 0.20 was chosen for the built-in hashing
    # embedder by inspecting data/eval/policy_questions.jsonl — the SAME set used for evaluation, so
    # the abstention results are optimistic. Re-tune it if you change EMBEDDING_PROVIDER.
    rag_min_similarity: float = 0.20

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_key) and bool(self.llm_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
