# ServiceSaathi AI Lab

> **Learning demo — fictional providers and simulated bookings.**

A full-stack home-service booking app for learning and interview demonstrations. A customer types
*"My kitchen tap is leaking. I need a plumber tomorrow morning in Wakad."* and the app:

1. predicts the service category with a **trained TF-IDF + logistic regression** model,
2. extracts area, date and time (showing that "tomorrow" means **Mon 02 Nov 2026**),
3. asks focused questions for anything missing or ambiguous,
4. finds matching technicians and free one-hour slots with **SQL**,
5. shows an **editable** summary with visiting charges from the database,
6. books only after explicit confirmation, **transactionally**, with double-booking made impossible
   by PostgreSQL constraints,
7. answers policy questions with **RAG over pgvector**, citing document title, version and section,
   and abstaining when the documents don't support an answer.

It covers plumbing, electrical repairs and appliance servicing in Wakad, Hinjawadi, Baner and Aundh,
with 12 fictional technicians. No real payments, messaging, dispatch, maps or customer data.

## What is real, simulated and optional

| | |
|---|---|
| **Implemented and tested** | Booking rules and constraints, concurrency control, idempotency, status machine, role/ownership checks, ML training + evaluation, rules extraction, RAG ingestion/versioning/retrieval/abstention/citations, Learning Lab, Developer Mode, audit log |
| **Simulated data** | Technicians, slots, demo accounts, policies (fictional company), ML training data (synthetic) |
| **Optional integrations** | Hosted LLM for extraction and grounded answers (Anthropic, OpenAI or OpenAI-compatible); semantic embeddings (local sentence-transformers or hosted). Written and unit-tested with mocked HTTP; **not run against a live provider** in the reference run |
| **Without any AI key** | Everything works: ML + SQL + bookings; *labelled* rules-based extraction; *labelled* retrieval-only policy excerpts |

## Quick start (Docker)

Requires Docker with Compose.

```bash
cp .env.example .env
docker compose up --build
```

Open **http://localhost:8000**. The app container applies migrations, trains the model if needed,
seeds demo data into an empty database and serves the UI and API (OpenAPI docs at `/docs`).

> The Compose file was validated and the container's start script was run against a fresh
> database, but the image build itself was not executed in the reference environment (no Docker
> Hub access there). See `docs/evaluation-report.md`.

### Demo accounts (password `demo1234`)

| Account | Role |
|---|---|
| `asha@demo.servicesaathi.local`, `rohan@demo.servicesaathi.local` | Customer |
| `provider01@…` … `provider12@demo.servicesaathi.local` | Provider (technician 1–12, e.g. 01 Ramesh Kulkarni, 03 Imran Shaikh) |
| `admin@demo.servicesaathi.local` | Admin |

## Local development (without the app container)

Requires Python 3.13, Node 22 and PostgreSQL 16 with pgvector. The easiest database is the
Compose one:

```bash
cp .env.example .env              # DATABASE_URL already points at the compose db
docker compose up -d db

cd backend
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
alembic upgrade head              # create tables, constraints, indexes, trigger
python -m app.services.ml.train   # train + evaluate the classifier (a few seconds)
python -m app.seed                # demo data, policies (ingested into pgvector), model registry
uvicorn app.main:app --reload     # API on http://localhost:8000

# second terminal
cd frontend
npm ci
npm run dev                       # UI on http://localhost:5173 (proxies /api to :8000)
```

To serve the built UI from FastAPI instead: `cd frontend && npm run build`, then open :8000.

## Tests, training and evaluation

```bash
cd backend
# tests use a separate database
docker compose exec db createdb -U servicesaathi servicesaathi_test
TEST_DATABASE_URL=postgresql+psycopg://servicesaathi:servicesaathi-local@localhost:5432/servicesaathi_test \
  python -m pytest -q

python -m app.services.ml.dataset            # regenerate the synthetic dataset
python -m app.services.ml.train              # train + evaluate; writes artifacts/classifier_report.json
python -m app.services.ml.classifier "Fridge is not cooling"   # predict

python -m app.evaluation.run                 # all suites: ml, extraction, retrieval, policy
python -m app.evaluation.run --suite policy  # one suite (results stored in evaluation_runs)

# optional browser walkthrough (pip install playwright && playwright install chromium)
python scripts/e2e_walkthrough.py
```

### Reference results (1 Nov 2026 — details in `docs/evaluation-report.md`)

| Check | Result |
|---|---|
| Automated tests | **76 passed** |
| ML held-out test accuracy / macro-F1 | model **0.81 / 0.81** · keyword baseline **0.88 / 0.93** — *the baseline wins on this synthetic data* |
| Extraction (25 labelled cases, rules) | 23 fully correct · field accuracy 0.97 |
| Retrieval recall@4 (24 labelled questions) | 0.96 |
| Policy suite (36 questions) | 22/22 supported answered · 5/6 unsupported abstained · 4/4 routed · 24/24 citations valid · 3/3 injection probes contained |
| Concurrent double booking | exactly one of two simultaneous confirmations succeeds (test + lab) |

## Using a hosted LLM (optional)

Set in `.env`, then restart:

```bash
LLM_PROVIDER=anthropic            # or openai, or openai_compatible (+ LLM_BASE_URL)
LLM_MODEL=<a model your account can use>
LLM_API_KEY=<your key>            # stays on the server; never sent to the browser
LLM_INPUT_PRICE_PER_MTOK=...      # optional, only for a labelled cost estimate
LLM_OUTPUT_PRICE_PER_MTOK=...
```

The LLM can only propose extraction fields (validated against the user's own words) and phrase
answers from retrieved passages (citations validated). The category always comes from the trained
classifier. Any failure falls back to the labelled non-LLM path.

**Semantic embeddings:** `EMBEDDING_PROVIDER=local` needs `pip install -r
requirements-local-embeddings.txt` and downloads a ~90 MB model **once** from Hugging Face on first
use (cached; in Docker, in the `hf-cache` volume). `EMBEDDING_PROVIDER=openai` uses a hosted API.
After switching, re-ingest documents (`python -m app.services.rag.reingest`) and re-tune
`RAG_MIN_SIMILARITY`.

## Project structure

```
backend/
  app/
    main.py              FastAPI app, health check, serves built UI
    config.py  db.py  models.py  schemas.py  auth.py  time_utils.py  seed.py  bootstrap.py
    routers/             core (auth, search, bookings), requests, provider, admin, policy, labs
    services/
      extraction.py      request extraction (rules + LLM) with provenance
      ml/                dataset, baseline, train, classifier, registry
      matching.py        technician matching (read-only SQL)
      booking.py slots.py  booking rules, provider slots
      rag/               chunking, ingest, retrieval, answer generation
      llm/providers.py   provider-agnostic LLM + embedding adapters
      audit.py trace.py trace_store.py sql_lab.py
    evaluation/          run.py, extraction_eval.py, policy_eval.py
  migrations/            Alembic; 0001 holds every table, constraint and trigger
  data/                  policies/, eval/, ml/
  tests/                 76 tests
  scripts/               start.sh (container entrypoint), e2e_walkthrough.py
frontend/src/            React + TypeScript: pages/, labs/, components/
docs/                    architecture, API, learning guide, ADRs, demo script, limitations, evaluation report, milestones
```

## Documentation

* [Architecture and booking sequence diagrams](docs/architecture.md)
* [API reference](docs/api.md) (plus live OpenAPI at `/docs`)
* [Learning guide, milestone by milestone](docs/learning-guide.md)
* ADRs: [booking integrity](docs/adr/0001-database-enforced-booking-integrity.md) ·
  [classical ML for category](docs/adr/0002-classical-ml-for-category.md) ·
  [pgvector and offline-first AI](docs/adr/0003-pgvector-and-offline-first-ai.md)
* [Five-minute interview demo script](docs/demo-script.md)
* [Known limitations and production gaps](docs/limitations.md)
* [Evaluation report with actual results](docs/evaluation-report.md)
* [Milestone checklist](docs/milestones.md)
