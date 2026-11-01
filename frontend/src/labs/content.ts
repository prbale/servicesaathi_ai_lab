// Written content for each Learning Lab module. Each lab works on its own.
export type LabContent = {
  id: string;
  title: string;
  concept: string;
  purpose: string;
  inputs: string;
  outputs: string;
  files: { path: string; what: string }[];
  mistakes: string[];
  exercise: { task: string; expected: string };
};

export const LABS: LabContent[] = [
  {
    id: "api",
    title: "Python and API",
    concept:
      "An API is a contract: the client sends JSON, the server checks it against a schema, then either does the work or explains exactly what was wrong. FastAPI turns Pydantic classes into that contract, including automatic validation and the /docs page.",
    purpose: "Every screen in this app talks to FastAPI. Validation at the edge means bad data never reaches booking rules or SQL.",
    inputs: "An HTTP method, a path, a bearer token and a JSON body.",
    outputs: "A status code (200, 201, 401, 403, 404, 409, 422) and a JSON body. 422 lists each invalid field.",
    files: [
      { path: "backend/app/schemas.py", what: "SearchIn, BookingIn and other request schemas" },
      { path: "backend/app/main.py", what: "validation_error() makes 422 responses readable" },
      { path: "backend/app/routers/core.py", what: "search() and create_booking() endpoints" },
      { path: "backend/app/auth.py", what: "current_user() and require_role() run on every protected call" },
    ],
    mistakes: [
      "Trusting the client: the UI hides buttons, but only the server decides who may do what.",
      "Returning 200 with an error message inside; use the status code so clients can react.",
      "Validating in the frontend only. Anyone can call the API directly, like this lab does.",
    ],
    exercise: {
      task: "Send the search request with category set to \"carpentry\" and preferred_date set to \"next week\".",
      expected: "422 with two errors: category must be one of plumbing/electrical/appliance, and preferred_date is not a valid date.",
    },
  },
  {
    id: "sql",
    title: "SQL",
    concept:
      "Relational databases store facts in tables and combine them with JOINs. Constraints (primary keys, foreign keys, CHECK, UNIQUE, EXCLUDE) make some mistakes impossible rather than merely unlikely. Indexes make lookups fast and some of them also enforce rules.",
    purpose: "Availability, charges and bookings always come from PostgreSQL. The model and the documents never decide what is free or what it costs.",
    inputs: "A query chosen from a fixed catalogue plus validated parameters. You cannot type your own SQL here.",
    outputs: "Columns and rows from a READ ONLY transaction, or the query plan when you tick EXPLAIN.",
    files: [
      { path: "backend/migrations/versions/0001_initial_schema.py", what: "Every table, constraint, index and the slot-protection trigger" },
      { path: "backend/app/services/matching.py", what: "build_query() — the technician search used by the app" },
      { path: "backend/app/services/sql_lab.py", what: "The query catalogue and the read-only runner" },
    ],
    mistakes: [
      "Building SQL with string formatting. Always bind parameters (:category), as every query here does.",
      "Storing local time without a zone. We store timestamptz and convert to Asia/Kolkata only for display.",
      "Relying on a SELECT-then-INSERT check to prevent duplicates. Only a constraint or a lock is safe under concurrency.",
    ],
    exercise: {
      task: "Run “Indexes and constraints that protect bookings” and find the index that allows one active booking per slot.",
      expected: "bookings_one_active_per_slot: a UNIQUE index on (slot_id) WHERE status IN (confirmed, en_route, in_progress, completed).",
    },
  },
  {
    id: "ml",
    title: "Machine learning",
    concept:
      "A classifier learns from labelled examples. TF-IDF turns text into numbers that weigh distinctive words and character fragments; logistic regression learns how much each feature points to each category. Scores are estimates, not guaranteed probabilities.",
    purpose: "Predicts plumbing, electrical or appliance from the customer's words. Below a validation-chosen threshold the app asks instead of guessing.",
    inputs: "Free text describing a problem.",
    outputs: "A score per category, the top features behind the prediction, the keyword baseline's answer and the saved evaluation report.",
    files: [
      { path: "backend/app/services/ml/dataset.py", what: "Template-based synthetic data with group ids" },
      { path: "backend/app/services/ml/train.py", what: "split_by_group(), choose_threshold(), train()" },
      { path: "backend/app/services/ml/classifier.py", what: "predict(), explain()" },
      { path: "backend/app/services/ml/baseline.py", what: "The keyword baseline" },
    ],
    mistakes: [
      "Letting paraphrases of one sentence land in both training and test (leakage), which inflates scores.",
      "Skipping a baseline. In this project the keyword baseline actually scores higher on the synthetic test set — read the report to see why.",
      "Treating synthetic test accuracy as real-world accuracy.",
    ],
    exercise: {
      task: "Type “Water heater trips the switch”. Compare the model's top two scores with the threshold.",
      expected: "An ambiguous request: electrical and appliance both score noticeably. If the top score is below the threshold the app asks the customer to choose.",
    },
  },
  {
    id: "extraction",
    title: "Extraction",
    concept:
      "Extraction turns a sentence into structured fields. Each value records its source: your exact words, an inference (“tomorrow” → a date), the ML model, an LLM proposal or your own edit. Anything missing becomes a focused question.",
    purpose: "Fills the editable booking summary without inventing an area, a time or a category.",
    inputs: "A customer sentence.",
    outputs: "Validated fields with provenance, missing fields, follow-up questions and notes. With an LLM configured you see both methods side by side.",
    files: [
      { path: "backend/app/services/extraction.py", what: "rules_extract(), llm_extract(), apply_overrides()" },
      { path: "backend/app/services/llm/providers.py", what: "Provider-agnostic complete_json()" },
      { path: "backend/data/eval/extraction_cases.jsonl", what: "Labelled cases for field accuracy" },
    ],
    mistakes: [
      "Accepting an LLM's output without checking it against the user's words.",
      "Silently resolving “tomorrow” without showing the calendar date.",
      "Letting the extraction step trigger actions; here it can only read the locality list.",
    ],
    exercise: {
      task: "Enter “MCB keeps tripping. I am in Kothrud, tomorrow afternoon”.",
      expected: "Locality is missing with a note that Kothrud is not served; date resolves to tomorrow's calendar date; time window is afternoon.",
    },
  },
  {
    id: "rag",
    title: "Retrieval-augmented generation",
    concept:
      "RAG answers from documents: split them into chunks, turn each chunk into a vector, find the chunks nearest to the question, then answer only from those chunks with citations. If nothing is close enough, abstain.",
    purpose: "Answers policy questions (charges, cancellation, coverage, safety) with verifiable sources, while live facts go to SQL.",
    inputs: "A question and the number of chunks to retrieve (k).",
    outputs: "Every chunk with its similarity score, the threshold, the routing decision and the final answer or abstention.",
    files: [
      { path: "backend/app/services/rag/chunking.py", what: "parse(), split(), detect_injection()" },
      { path: "backend/app/services/rag/ingest.py", what: "Versioned ingestion: draft → active → superseded" },
      { path: "backend/app/services/rag/retrieval.py", what: "pgvector cosine search over active chunks" },
      { path: "backend/app/services/rag/answer.py", what: "detect_route(), answer_question(), citation validation" },
    ],
    mistakes: [
      "Answering when retrieval found nothing relevant. A confident wrong answer is worse than “I don't know”.",
      "Searching superseded document versions.",
      "Treating document text as instructions. Retrieved text is data and may contain prompt injection.",
    ],
    exercise: {
      task: "Ask “Is there a cancellation fee if I cancel 3 hours before?” and look at the cited version.",
      expected: "The answer cites Cancellation and Rescheduling version 2 (free until 2 hours before). Version 1, with its 4-hour rule and fee, is superseded and never retrieved.",
    },
  },
  {
    id: "booking",
    title: "Booking rules",
    concept:
      "When two people confirm the same slot at the same moment, both may pass an availability check. The fix is in the database: lock the slot row inside a transaction, and back it with a unique index so a second active booking is impossible.",
    purpose: "Guarantees exactly one booking per slot, idempotent retries, valid status changes and cancellation by policy.",
    inputs: "Optional slot id (otherwise the next free slot at least 3 hours ahead).",
    outputs: "What each of the two simultaneous attempts got back, the validation checks each ran, and the actual rows in the bookings table.",
    files: [
      { path: "backend/app/services/booking.py", what: "create_booking(), change_status(), TRANSITIONS" },
      { path: "backend/migrations/versions/0001_initial_schema.py", what: "bookings_one_active_per_slot, protect_booked_slots()" },
      { path: "backend/tests/test_booking_rules.py", what: "test_concurrent_confirmations_exactly_one_wins" },
    ],
    mistakes: [
      "Checking availability in the frontend and assuming it still holds when the user clicks Confirm.",
      "Retrying a timed-out request without an idempotency key, creating duplicates.",
      "Deleting cancelled bookings, losing the history that explains what happened.",
    ],
    exercise: {
      task: "Run the race three times.",
      expected: "Every time: one success and one conflict with alternatives offered; the bookings table shows exactly one active booking for the slot, and the cleanup cancels it.",
    },
  },
  {
    id: "evaluation",
    title: "Evaluation",
    concept:
      "Evaluation checks behaviour against labelled expectations, repeatably. Automated metrics (accuracy, recall@k, abstention rate, citation validity) are kept separate from human judgements of answer quality, which no script can fill in.",
    purpose: "Shows where each component works and where it fails, with real numbers from this machine.",
    inputs: "A suite: ml, extraction, retrieval or policy.",
    outputs: "The stored run with its summary and every failing case.",
    files: [
      { path: "backend/app/evaluation/run.py", what: "run_suite() stores results in evaluation_runs" },
      { path: "backend/app/evaluation/policy_eval.py", what: "36 policy questions and the injection probe" },
      { path: "backend/app/evaluation/extraction_eval.py", what: "Field accuracy with a frozen clock" },
    ],
    mistakes: [
      "Tuning thresholds on the same questions you report on, then calling the result unbiased. This project does that for the RAG threshold and says so.",
      "Hiding failures. Read them: they are the most useful output.",
      "Reporting a single number without its sample size.",
    ],
    exercise: {
      task: "Run the policy suite and open its failures.",
      expected: "One known failure: “What is the salary of a technician?” is not abstained, because lexical retrieval finds word overlap. With an LLM configured, the model's insufficient-evidence flag catches it.",
    },
  },
  {
    id: "deployment",
    title: "Deployment",
    concept:
      "Deployment packages code and configuration so it runs the same way elsewhere. Containers hold the app; environment variables hold settings and secrets; migrations evolve the database schema; health checks tell the platform whether the app is ready.",
    purpose: "docker compose up starts PostgreSQL with pgvector and the app. The app container migrates, seeds, trains the model and then serves the API and UI on one port.",
    inputs: "Environment variables from .env (see .env.example).",
    outputs: "Which settings are set (never their secret values), the migration revision, the loaded model version and the health status.",
    files: [
      { path: "docker-compose.yml", what: "db and app services, health checks, volumes" },
      { path: "Dockerfile", what: "Builds the React UI, then the Python image" },
      { path: "backend/scripts/start.sh", what: "migrate → seed if empty → train if missing → serve" },
      { path: "backend/app/main.py", what: "health() endpoint used by the container health check" },
    ],
    mistakes: [
      "Committing .env or API keys. Only .env.example belongs in git.",
      "Changing the database by hand instead of writing a migration.",
      "Reporting healthy before the database and model are actually ready.",
    ],
    exercise: {
      task: "Open /api/health in a new tab, then stop the database and refresh.",
      expected: "200 with database ok and the model version; after stopping the database, 503 with database.ok = false.",
    },
  },
];
