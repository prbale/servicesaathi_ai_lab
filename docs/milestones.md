# Milestone checklist

Each milestone is a git commit; `git log --oneline` lists them. The app was runnable and its tests
green at the end of each backend milestone. The React UI was written in milestone 6 (earlier
milestones were exercised through the API, tests and OpenAPI `/docs`).

| # | Milestone | Status | Evidence |
|---|---|---|---|
| 1 | SQL-backed directory and booking | ✅ Done | Migration `0001`, `seed.py`, `matching.py`, booking API; UI form flow added in M6 |
| 2 | Conflict prevention and automated tests | ✅ Done | Row lock + partial unique index + idempotency; 25 booking tests incl. concurrency |
| 3 | ML classification and evaluation | ✅ Done (baseline still wins — documented) | `services/ml/*`, report, 6 tests |
| 4 | Natural-language extraction | ✅ Done | Rules + provider-agnostic LLM path with validation; 25-case eval; 13 tests |
| 5 | RAG policy answers | ✅ Done | Versioned ingestion, quarantine, pgvector retrieval, routing, abstention, 36-question eval; 20 tests |
| 6 | Learning labs and developer traces | ✅ Done | 8 labs, Developer Mode with replay; 12 tests; browser walkthrough |
| 7 | Containerised deployment and documentation | ✅ Written · ⚠️ image build not executed here | Dockerfile, compose (config-validated), `start.sh` run on a fresh DB; docs/ |

## Acceptance criteria

| Criterion | Status |
|---|---|
| Unstructured request → confirmed, persisted booking | ✅ API test + browser walkthrough |
| Missing details trigger clarification | ✅ |
| Availability and charges from the database | ✅ `test_charges_come_from_database`, live routing |
| Double booking prevented under concurrency | ✅ two-thread test + DB-level test + race lab |
| ML model genuinely trained and evaluated | ✅ (and it loses to the baseline on synthetic test data — reported) |
| Policy answers use real retrieval and verifiable citations | ✅ 24/24 citations valid |
| Unsupported questions trigger abstention | ⚠️ 5/6 in retrieval-only mode; known lexical-retrieval miss |
| Useful, honestly labelled mode without hosted AI credentials | ✅ default mode |
| Each concept explorable independently in the Learning Lab | ✅ 8 labs |
| Setup and tests executed, actual outcomes reported | ✅ `docs/evaluation-report.md` (Docker build not executed) |
