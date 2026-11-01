"""Keyword baseline: count category keywords, pick the most frequent.

Every ML model should be compared with something this simple. If the model cannot
beat it clearly, the model is not earning its complexity.
"""
import re

KEYWORDS = {
    "plumbing": ["tap", "leak", "pipe", "drain", "toilet", "flush", "plumber", "sink", "faucet", "water pressure",
                 "shower", "tank", "seepage", "clog", "blocked", "drainage", "valve", "basin"],
    "electrical": ["switch", "socket", "mcb", "wiring", "wire", "electrician", "fan", "light", "spark", "shock",
                   "power", "fuse", "short circuit", "plug", "earthing", "voltage", "inverter", "tube light"],
    "appliance": ["washing machine", "fridge", "refrigerator", "microwave", "geyser", "purifier", "ro ", "mixer",
                  "dishwasher", "oven", "chimney", "fryer", "washer", "dispenser", "induction", "vacuum", "kettle"],
}


def predict(text: str) -> dict:
    t = f" {text.lower()} "
    counts = {c: sum(1 for k in kws if re.search(r"\b" + re.escape(k.strip()) + r"\b", t)) for c, kws in KEYWORDS.items()}
    best = max(counts.values())
    winners = [c for c, n in counts.items() if n == best]
    if best == 0 or len(winners) > 1:
        return {"category": None, "counts": counts, "reason": "no keyword" if best == 0 else "tie"}
    return {"category": winners[0], "counts": counts, "reason": "most keyword matches"}
