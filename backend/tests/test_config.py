"""Settings must accept .env.example exactly as shipped (blank optional values)."""
from app.config import BACKEND_DIR, Settings


def _example_env() -> dict[str, str]:
    lines = (BACKEND_DIR.parent / ".env.example").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if line.strip() and not line.startswith("#"))


def test_env_example_loads_with_blank_optional_values(monkeypatch):
    env = _example_env()
    assert env["LLM_INPUT_PRICE_PER_MTOK"] == ""  # the case that broke docker compose
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.llm_input_price_per_mtok is None and s.llm_output_price_per_mtok is None
    assert s.llm_enabled is False and s.rag_min_similarity == 0.20


def test_prices_are_parsed_when_given(monkeypatch):
    monkeypatch.setenv("LLM_INPUT_PRICE_PER_MTOK", "3")
    assert Settings(_env_file=None).llm_input_price_per_mtok == 3.0
