# ADR 0002 — Use a trained TF-IDF + logistic regression classifier for the service category

**Status:** accepted · **Date:** 2026-11-01

## Context

Every request must be routed to plumbing, electrical or appliance servicing. Wrong routing sends
the wrong trade to a home. The app must also work with no hosted AI key.

## Options considered

1. **Keyword rules.** Transparent and fast, but brittle to new phrasing and hand-maintained.
2. **Ask the LLM for the category.** Flexible, but needs a key, costs per request, is harder to
   evaluate reproducibly, and its confidence is not well defined.
3. **Classical ML: TF-IDF (word + character n-grams) + logistic regression (chosen).** Trains in
   seconds, runs offline, produces per-class scores, and is easy to inspect (feature weights).

## Decision

Option 3 is the only source of `predicted_category`, in both rules and LLM extraction modes. A
low-confidence threshold chosen on validation data makes the app ask instead of guessing. A
keyword baseline is always reported alongside it.

## Consequences

* The pipeline is real and repeatable: grouped splits (no paraphrase leakage), C chosen on
  validation, threshold chosen on validation with an explicit utility, held-out test metrics.
* **Honest result:** on the synthetic held-out templates the keyword baseline currently scores
  higher (accuracy 0.88 vs 0.81). Reasons: small, template-generated data; few test groups; and the
  baseline keywords were written by the same author as the data. This is reported in the ML Lab and
  the evaluation report, not hidden. Dataset v1 (20 templates/category) scored 0.71; adding varied
  templates (v2) raised it to 0.81.
* Scores are treated as estimates, not calibrated probabilities. The threshold catches only part
  of the out-of-scope requests; the UI therefore always lets users change the category.
* Adding a category requires new labelled data and retraining, so admins cannot add categories
  from the UI — they can only rename them.
* Next step for a real product: collect real (consented, anonymised) requests, label them, and
  re-evaluate; consider combining model and baseline disagreement as an extra "ask" signal.
