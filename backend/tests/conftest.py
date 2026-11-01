"""Test setup: a separate PostgreSQL database, migrated and freshly seeded.

Set TEST_DATABASE_URL to override. Tests never touch the development database.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/servicesaathi_test"
)
os.environ["DATABASE_URL"] = TEST_DB
os.environ["LLM_PROVIDER"] = "none"  # tests never call a real hosted model
os.environ["EMBEDDING_PROVIDER"] = "hashing"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import reset_engine  # noqa: E402

get_settings.cache_clear()
reset_engine()


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    env = {**os.environ, "DATABASE_URL": TEST_DB}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True,
                   capture_output=True)
    yield


@pytest.fixture()
def seeded(migrated_db):
    """Fresh business data for each test that asks for it."""
    from app.seed import seed_all

    return seed_all(with_policies=False, with_model=False)


@pytest.fixture()
def client():
    from app.main import app

    return TestClient(app)


def login(client, email: str, password: str = "demo1234") -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


ASHA = "asha@demo.servicesaathi.local"
ROHAN = "rohan@demo.servicesaathi.local"
ADMIN = "admin@demo.servicesaathi.local"


def provider(i: int) -> str:
    return f"provider{i:02d}@demo.servicesaathi.local"
