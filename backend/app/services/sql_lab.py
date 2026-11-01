"""SQL Lab: a fixed catalogue of read-only queries.

Learners pick a query and fill in validated parameters. The SQL text is fixed in this
file — users can NEVER submit their own SQL. Each run happens in a READ ONLY
transaction with a statement timeout, so even a bug here could not change data.
No query returns emails, password hashes or other personal data.
"""
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import time_utils as tu

ACTIVE = "('confirmed','en_route','in_progress','completed')"

QUERIES: dict[str, dict] = {
    "technicians_for_job": {
        "title": "Technicians who offer a category in a locality",
        "concepts": ["INNER JOIN", "WHERE filters", "composite primary keys"],
        "params": {"category": ["plumbing", "electrical", "appliance"], "locality": ["wakad", "hinjawadi", "baner",
                                                                                     "aundh"]},
        "sql": """SELECT t.id, t.name, tc.visiting_charge_inr, t.rating
FROM technicians t
JOIN technician_categories tc ON tc.technician_id = t.id
JOIN technician_service_areas sa ON sa.technician_id = t.id
WHERE tc.category_code = :category
  AND sa.locality_code = :locality
  AND t.is_active
ORDER BY tc.visiting_charge_inr""",
        "explain": "Each JOIN keeps only rows that match on both sides. The two link tables turn the "
                   "many-to-many relationships (technician↔category, technician↔locality) into rows we can filter.",
    },
    "free_slots_tomorrow": {
        "title": "Free slots per technician tomorrow",
        "concepts": ["NOT EXISTS anti-join", "GROUP BY", "timestamptz and time zones"],
        "params": {},
        "sql": f"""SELECT t.name, count(*) AS free_slots,
       min(s.start_at AT TIME ZONE 'Asia/Kolkata') AS first_free_local
FROM availability_slots s
JOIN technicians t ON t.id = s.technician_id
WHERE s.start_at >= :day_start AND s.start_at < :day_end
  AND NOT s.is_withdrawn
  AND NOT EXISTS (SELECT 1 FROM bookings b
                  WHERE b.slot_id = s.id AND b.status IN {ACTIVE})
GROUP BY t.name
ORDER BY free_slots DESC""",
        "explain": "NOT EXISTS keeps slots that have no active booking. Times are stored as absolute instants "
                   "(timestamptz) and converted to Kolkata wall-clock time only for display.",
    },
    "booking_status_counts": {
        "title": "Bookings by status",
        "concepts": ["GROUP BY", "aggregate functions"],
        "params": {},
        "sql": "SELECT status, count(*) AS bookings FROM bookings GROUP BY status ORDER BY bookings DESC",
        "explain": "GROUP BY collapses rows with the same status into one row; count(*) counts each group.",
    },
    "charges_by_category": {
        "title": "Visiting charge range per category",
        "concepts": ["MIN / MAX / AVG", "ROUND"],
        "params": {},
        "sql": """SELECT category_code, min(visiting_charge_inr) AS min_inr, max(visiting_charge_inr) AS max_inr,
       round(avg(visiting_charge_inr)) AS avg_inr, count(*) AS technicians
FROM technician_categories GROUP BY category_code ORDER BY category_code""",
        "explain": "This is how the policy assistant answers 'how much does a plumber charge?': from live data, "
                   "not from a document.",
    },
    "booked_slots": {
        "title": "Slots that currently hold an active booking",
        "concepts": ["partial unique index", "JOIN"],
        "params": {},
        "sql": f"""SELECT b.reference, b.status, t.name AS technician,
       s.start_at AT TIME ZONE 'Asia/Kolkata' AS starts_local
FROM bookings b
JOIN availability_slots s ON s.id = b.slot_id
JOIN technicians t ON t.id = b.technician_id
WHERE b.status IN {ACTIVE}
ORDER BY s.start_at""",
        "explain": "The partial unique index bookings_one_active_per_slot allows at most ONE row here per slot. "
                   "That index, not the UI, is what makes double booking impossible.",
    },
    "booking_indexes": {
        "title": "Indexes and constraints that protect bookings",
        "concepts": ["indexes", "constraints", "system catalogs"],
        "params": {},
        "sql": """SELECT indexname, indexdef FROM pg_indexes
WHERE tablename IN ('bookings', 'availability_slots') ORDER BY tablename, indexname""",
        "explain": "Indexes speed up lookups; UNIQUE and EXCLUDE ones also enforce rules. Look for "
                   "bookings_one_active_per_slot (partial unique) and slots_no_overlap (exclusion).",
    },
    "policy_versions": {
        "title": "Policy document versions and their status",
        "concepts": ["versioning", "partial unique index"],
        "params": {},
        "sql": """SELECT doc_key, version, status, ingestion_status, chunk_count
FROM policy_documents ORDER BY doc_key, version""",
        "explain": "Only 'active' versions are searched by RAG. A partial unique index allows one active "
                   "version per document.",
    },
}


class SqlLabError(ValueError):
    pass


def catalogue() -> list[dict]:
    return [{"id": k, **{f: v[f] for f in ("title", "concepts", "params", "sql", "explain")}}
            for k, v in QUERIES.items()]


def run(db: Session, query_id: str, params: dict, explain: bool = False) -> dict:
    q = QUERIES.get(query_id)
    if q is None:
        raise SqlLabError("Unknown query.")
    bound: dict = {}
    for name, allowed in q["params"].items():
        value = params.get(name)
        if value not in allowed:
            raise SqlLabError(f"Parameter '{name}' must be one of {allowed}.")
        bound[name] = value
    if query_id == "free_slots_tomorrow":
        d = tu.today_local() + timedelta(days=1)
        bound["day_start"] = tu.local_dt(d, 0)
        bound["day_end"] = tu.local_dt(d, 0) + timedelta(days=1)
    db.rollback()
    db.execute(text("SET TRANSACTION READ ONLY"))
    db.execute(text("SET LOCAL statement_timeout = '2s'"))
    sql = ("EXPLAIN " if explain else "") + q["sql"]
    result = db.execute(text(sql), bound)
    cols = list(result.keys())
    rows = [[str(v) if v is not None else None for v in r] for r in result.fetchmany(200)]
    db.rollback()
    return {"query_id": query_id, "sql": q["sql"], "params": {k: str(v) for k, v in bound.items()},
            "columns": cols, "rows": rows, "explain": explain, "read_only": True}
