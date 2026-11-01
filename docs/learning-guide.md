# Learning guide — build it milestone by milestone

This guide follows the order the project was built in. Each milestone left the app runnable, and
each one has a git commit you can check out (`git log --oneline`) to see the code at that stage.
Pair each step with its Learning Lab module in the app.

Before starting: read the README's setup, sign in as **Asha**, and book the example request once.
Then turn on **Developer mode** and repeat it — the right-hand panel shows every step below.

---

## Milestone 1 — A SQL-backed directory and form booking

**Goal:** store technicians, the services they offer, where they work and when they are free;
find matches with SQL; create a booking.

Read, in order:
1. `backend/migrations/versions/0001_initial_schema.py` — every table. Notice the *link tables*
   `technician_categories` and `technician_service_areas`: a many-to-many relationship becomes rows.
2. `backend/app/seed.py` — 12 fictional technicians, slots generated relative to today with a fixed
   random seed (reproducible per day).
3. `backend/app/services/matching.py` → `build_query()` — one SELECT joining four tables, with a
   `NOT EXISTS` sub-query to skip slots that already have an active booking.

Try: SQL Lab → "Technicians who offer a category in a locality". Change the parameters.

Key idea: **availability and prices are facts in the database.** Nothing else in the system is
allowed to make them up.

## Milestone 2 — Conflict prevention and automated tests

**Goal:** make double booking impossible, and prove it.

Read `backend/app/services/booking.py` → `create_booking()` top to bottom. The order matters:
1. Idempotency lookup — a retried request returns the original booking.
2. `SELECT ... FOR UPDATE` on the slot — a concurrent confirmation now *waits*.
3. Validation — slot exists, belongs to the technician, is in the future, technician offers the
   category and serves the locality.
4. "Is the slot already taken?" — reliable now, because we hold the lock.
5. Insert + status event + audit, then commit. The unique index is the last line of defence.

Then read `backend/tests/test_booking_rules.py`:
* `test_concurrent_confirmations_exactly_one_wins` uses two threads, two DB sessions and a barrier
  so both confirm at the same instant.
* `test_database_index_blocks_double_booking_even_without_app_checks` bypasses the service and
  inserts directly — the index still refuses.

Try: Booking Rules Lab → Run the race. Run `pytest tests/test_booking_rules.py -v`.

## Milestone 3 — ML classification and evaluation

**Goal:** a real, honestly evaluated classifier.

1. `services/ml/dataset.py` — synthetic examples built from templates. Each template's paraphrases
   share a **group** id.
2. `services/ml/train.py` → `split_by_group()` — whole groups go to train, validation or test. If
   paraphrases of one sentence appeared in both train and test, the test would measure memory, not
   generalisation (**leakage**).
3. `build_pipeline()` — TF-IDF of words (1–2 grams) and characters (3–5 grams), then logistic
   regression. Character n-grams help with typos and word forms.
4. `choose_threshold()` — picks the confidence threshold on **validation** data using an explicit
   cost: a silent wrong guess costs more than asking.
5. The report compares the model with `baseline.py` (keyword counting).

**What actually happened (a real lesson).** The first dataset (v1, 20 templates per category)
gave the model 0.71 test accuracy — *below* the keyword baseline's 0.90. Inspecting the errors
showed the cause: each template had its own vocabulary, so held-out templates used words the model
had never seen ("electrician", "shock"), while the hand-written keyword list already knew them.
Dataset v2 added varied templates that reuse everyday words; the model rose to 0.81. The baseline
still scores higher (0.88) on this synthetic test. That is reported, not hidden — see ADR 0002.
The v1 report is kept at `backend/data/ml/classifier_report_dataset_v1.json`.

Also note the threshold-grid bug that was fixed: with three classes the top score is always at
least 1/3, so a threshold below 0.34 means "never ask". The grid now starts at 0.40.

Commands:
```bash
python -m app.services.ml.dataset     # regenerate data (deterministic)
python -m app.services.ml.train       # train + evaluate + save artifacts/
python -m app.services.ml.classifier "Fridge is not cooling"
```

## Milestone 4 — Natural-language extraction

**Goal:** turn a sentence into validated fields, never inventing anything.

Read `services/extraction.py`:
* `FieldValue.source` — `user_text`, `inferred`, `ml_model`, `llm`, `user_edit`, `missing`.
* `parse_date()` — "tomorrow", weekdays, "5 Nov", "05/11" (Indian DD/MM). Relative words are
  `inferred` and the UI always shows the resolved calendar date.
* `parse_locality()` — supported areas and aliases from the DB; an unsupported area becomes a
  note and a question, never a guess.
* `llm_extract()` — the LLM must copy evidence verbatim; the server rejects a locality, date or
  time whose evidence is not in the user's text, and cross-checks dates with the rules parser.
  The category always comes from the trained classifier.
* `apply_overrides()` — the user's corrections, validated again on the server.

Try: Extraction Lab with "MCB keeps tripping. I am in Kothrud, tomorrow afternoon".
Run: `python -m app.evaluation.run --suite extraction`.

## Milestone 5 — RAG policy answers

**Goal:** answer policy questions only from documents, with citations, and abstain otherwise.

1. `data/policies/*.md` — five fictional policies, plus a superseded v1 of the cancellation policy.
2. `rag/chunking.py` — section-aware chunks; `detect_injection()` quarantines instruction-like text.
3. `rag/ingest.py` — upload creates a *draft*; successful ingestion activates it and supersedes the
   old version in one transaction; a failed ingestion leaves the old version active.
4. `rag/retrieval.py` — cosine search with pgvector over active, non-quarantined chunks.
5. `rag/answer.py` — routing first (live facts go to SQL), then retrieval, abstention below the
   threshold, and either a validated LLM answer or labelled retrieval-only excerpts.

Try: RAG Lab with "Is there a cancellation fee if I cancel 3 hours before?" — only v2 is cited.

## Milestone 6 — Learning labs and developer traces

`routers/labs.py` exposes one endpoint group per lab; `services/trace.py` records timed steps.
Traces contain observable evidence (inputs, fields, SQL shape, passages, timings, token usage) and
never secrets or hidden reasoning. They are kept in memory per user (`trace_store.py`).

## Milestone 7 — Containers and documentation

`Dockerfile` builds the UI with Node, then a Python image that serves both API and UI.
`scripts/start.sh` runs migrations, `app.bootstrap` (train if missing, seed if empty) and uvicorn.
`docker-compose.yml` adds PostgreSQL + pgvector with a health check.

---

## Glossary

* **Transaction** — a group of SQL statements that succeed or fail together.
* **Row lock (`FOR UPDATE`)** — makes other transactions wait before changing the same row.
* **Partial unique index** — a uniqueness rule that applies only to rows matching a condition.
* **Idempotency key** — a client-chosen id that makes retries safe.
* **TF-IDF** — word weights that are high for words frequent in this text but rare overall.
* **Macro F1** — the average F1 across classes, so a small class counts as much as a large one.
* **Recall@k** — share of questions where a relevant passage is among the top k results.
* **Abstention** — declining to answer when evidence is insufficient.
* **Prompt injection** — text inside data that tries to act as instructions to a model.
