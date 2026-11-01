# Known limitations and production-readiness gaps

## What is real, simulated or optional

| Area | Status |
|---|---|
| Booking rules, constraints, concurrency control, idempotency, status transitions | **Implemented and tested** |
| Technician matching and charges from SQL | **Implemented** — data is **simulated** (12 fictional technicians) |
| ML classifier training/evaluation | **Implemented** — on **synthetic** data |
| Rules-based extraction | **Implemented**, evaluated on 25 labelled cases written by the author |
| Hosted-LLM extraction and answer generation | **Implemented, optional** — tested against mocked HTTP responses only; not run against a live provider in the reference run |
| RAG ingestion, versioning, retrieval, abstention, citations | **Implemented** with the built-in hashing embedder |
| Local / hosted semantic embeddings | **Optional integrations** — code paths written, not executed in the reference run |
| Policies | **Fictional** demo documents, not legal statements and not any real provider's terms |
| Payments, messaging, dispatch, maps, real customer data | **Not included** (out of scope) |
| Docker Compose | **Written and config-validated**; the image build was not executed in the reference environment (no access to Docker Hub). The same start sequence was run directly against a fresh database. |

## Known functional limitations

* **ML:** the keyword baseline outperforms the classifier on the synthetic held-out test
  (0.88 vs 0.81 accuracy). The low-confidence threshold catches only some out-of-scope requests
  (3 of 8 in test). Scores are not calibrated probabilities.
* **Extraction (rules):** a vague sentence such as "Something is wrong" is accepted as an issue
  description; an instruction-like request ("Ignore your rules and book…") is treated as an issue
  text. Both appear as evaluation failures.
* **Retrieval:** the hashing embedder is lexical. Unsupported questions that share words with the
  policies ("What is the salary of a technician?") pass the similarity threshold, so retrieval-only
  mode shows unrelated excerpts instead of abstaining. The threshold (0.20) was tuned on the same
  questions used for evaluation, so abstention metrics are optimistic.
* **Prompt injection:** instruction-like text is quarantined by pattern matching. **Content
  poisoning** that reads like ordinary policy ("All visits are free this month") cannot be detected
  this way; the mitigation is that only admins can upload documents and every version is audited.
* **Locality aliases** are a fixed list. Misspellings beyond the aliases are not matched.
* **Rescheduling** is cancel-and-rebook; there is no atomic move of a booking to another slot.
* **Traces** are kept in process memory (last 300) and are lost on restart; multiple app
  instances would each hold their own.
* **Time windows** are fixed (morning 08–12, afternoon 12–16, evening 16–20); slots are fixed
  one-hour blocks.
* **Policy "routing"** to live data uses keyword rules; unusual phrasings may go to the policy path.

## Gaps before production

Security and identity
* Replace demo PBKDF2 + HMAC tokens with a proper identity provider (OIDC), refresh tokens,
  revocation, MFA for admins, and per-user rate limiting / lockout.
* CSRF and CORS policy review, security headers, secrets in a secret manager, key rotation.
* Remove the shared demo password and the "accounts" shortcut on the login page.

Data and privacy
* Real addresses and phone numbers would need consent, encryption at rest, retention rules and
  data-subject request handling. Audit details are scrubbed of secrets but not formally reviewed.

Reliability and operations
* Background job queue for ingestion and evaluation (they run inside the request today).
* Structured logging, metrics, tracing (OpenTelemetry), alerting, backups and restore drills.
* Connection pooling limits tuned for load; load and soak testing of the booking path.
* Migrations for zero-downtime deploys; blue/green or rolling releases.

ML and AI
* Real labelled data, periodic re-evaluation, drift monitoring and a model registry with approvals.
* Calibrated confidence (e.g. isotonic calibration) before using scores as probabilities.
* A semantic embedding model, a separate tuning set for the abstention threshold, and
  human-reviewed answer quality at scale.
* LLM provider timeouts, retries with backoff, cost budgets and caching.

Product
* Payments, notifications, technician dispatch and maps are deliberately out of scope.
* Accessibility was considered (contrast, focus states, labels, reduced motion) but not audited
  with assistive technology.
