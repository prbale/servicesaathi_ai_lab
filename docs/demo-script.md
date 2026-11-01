# Five-minute interview demo script

Setup before the call: app running, signed out, browser at `http://localhost:8000`, a second
browser profile signed in as **Rohan**. Optionally reset demo data (Admin → Reset demo).

| Time | Do | Say |
|---|---|---|
| 0:00 | Show the login screen and the demo strip. | "A home-service booking app for four Pune localities. Everything is fictional and simulated, and it runs with or without a hosted AI key." |
| 0:20 | Sign in as Asha. Click **Use the example**, then **Find a technician**. | "One sentence in. A trained TF-IDF + logistic-regression model picks the trade; the extractor pulls area, day and time." |
| 0:50 | Point at the job card's small notes. | "Every field says where it came from — 'from your words: Wakad', 'inferred from tomorrow → Monday 02 November'. Nothing is invented; missing fields become questions." Click **Change** on the day to show it is editable. |
| 1:20 | Scroll to technicians. | "These come from SQL: category, locality and free slots, with the reasons each matched. The visiting charge is from the database and isn't the final repair price." |
| 1:40 | Pick a slot, show the review, press **Confirm booking**. | "Nothing is reserved until I confirm. The request carries an idempotency key, so a retry can't double book." Show the yellow ticket. |
| 2:10 | Turn on **Developer mode**, replay "Electrical hazard". | "Observable trace: extraction, classifier scores and model version, validation, timings, the audit reference. Note the safety notice — no DIY instructions." |
| 2:50 | Learning Lab → **Booking rules** → Run the race. | "Two customers confirm the same slot at the same instant on separate connections. Exactly one wins. That's a row lock plus a partial unique index — the database guarantees it, not the UI." |
| 3:30 | Learning Lab → **RAG**, ask "Is there a cancellation fee if I cancel 3 hours before?" | "Retrieval over active document versions only. Version 1 of this policy had a 4-hour rule; it's superseded and never retrieved. Below the similarity threshold it abstains." Ask "Do you offer car washing?" to show abstention. |
| 4:10 | Learning Lab → **ML**, open the report. | "Honest numbers: on synthetic held-out templates the keyword baseline actually beats the model, 0.88 vs 0.81. I kept that visible and wrote up why — small template data, author-biased baseline. Synthetic scores don't prove real-world accuracy." |
| 4:40 | Close. | "Trade-offs are in three ADRs; limitations and production gaps are listed. 76 automated tests plus evaluation suites, all run with real outcomes recorded." |

Likely follow-up questions and where the answers are:

* *Why not let the LLM pick the category?* → ADR 0002.
* *What if two requests race?* → ADR 0001, `test_concurrent_confirmations_exactly_one_wins`.
* *What about prompt injection?* → `rag/chunking.py::detect_injection`, the injection probe in
  `evaluation/policy_eval.py`, and the limitation that content poisoning without instruction-like
  wording is not detectable by pattern matching.
* *How would you productionise it?* → `docs/limitations.md`.
