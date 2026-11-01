# ADR 0001 — Enforce booking integrity in PostgreSQL, not in application code alone

**Status:** accepted · **Date:** 2026-11-01

## Context

The core promise is "a confirmed slot is yours". Two customers can open the same free slot and
press Confirm within milliseconds. A check-then-insert in Python (`if not taken: insert`) has a
race window: both requests can pass the check before either inserts. Retries after a network
timeout can also create duplicates.

## Options considered

1. **Frontend availability check only.** Trivially bypassed; stale the moment it is shown.
2. **Application check + insert, no locking.** Race window remains.
3. **Optimistic concurrency (version column on slots).** Works, but the loser must be detected
   and retried in code, and nothing stops a future code path from forgetting the check.
4. **Distributed lock (Redis etc.).** Extra infrastructure; the lock and the data can disagree.
5. **Pessimistic row lock + database constraint (chosen).** `SELECT ... FOR UPDATE` on the slot
   serialises confirmations; the partial unique index `bookings_one_active_per_slot` makes a
   second active booking impossible even if the lock were skipped. `UNIQUE (customer_id,
   idempotency_key)` makes retries return the original booking.

## Decision

Option 5, plus related rules as constraints: an exclusion constraint against overlapping slots,
composite foreign keys so a booking's technician must offer the category and serve the locality,
CHECKs for one-hour slots, and a trigger that protects booked slots from being moved or deleted.

## Consequences

* Correctness does not depend on every code path remembering a rule — the concurrency test
  (`test_concurrent_confirmations_exactly_one_wins`) and the direct-insert test prove both layers.
* The losing request waits briefly on the row lock (milliseconds here), then gets a clear 409 with
  freshly queried alternatives.
* Business rules are split between SQL and Python. Time-dependent rules (future slot, 2-hour
  cancellation cut-off) stay in Python because a CHECK constraint cannot depend on `now()`.
* Cancelled bookings are kept (status change, not delete), so the partial index only counts
  active statuses and history survives.
