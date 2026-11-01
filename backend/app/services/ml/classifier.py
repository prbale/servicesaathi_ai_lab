"""Load the saved classifier once and predict.

    python -m app.services.ml.classifier "My kitchen tap is leaking"
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np

from ...config import get_settings
from . import baseline


@lru_cache
def _load():
    path = Path(get_settings().model_dir) / "classifier.joblib"
    if not path.exists():
        return None
    return joblib.load(path)


def reload() -> None:
    _load.cache_clear()


def get_model_info() -> dict | None:
    m = _load()
    if m is None:
        return None
    return {"model_version": m["model_version"], "dataset_version": m["dataset_version"],
            "threshold": m["threshold"], "labels": m["labels"]}


def get_report() -> dict | None:
    path = Path(get_settings().model_dir) / "classifier_report.json"
    return json.loads(path.read_text()) if path.exists() else None


class ModelNotTrained(RuntimeError):
    pass


def predict(text: str) -> dict:
    m = _load()
    if m is None:
        raise ModelNotTrained("Classifier not trained. Run: python -m app.services.ml.train")
    pipe = m["pipeline"]
    probs = pipe.predict_proba([text])[0]
    classes = list(pipe.classes_)
    order = np.argsort(probs)[::-1]
    top = classes[int(order[0])]
    top_score = float(probs[order[0]])
    confident = bool(top_score >= m["threshold"])
    return {
        "category": top if confident else None,
        "top_category": top,
        "top_score": round(top_score, 4),
        "scores": {classes[i]: round(float(probs[i]), 4) for i in order},
        "threshold": m["threshold"],
        "confident": confident,
        "model_version": m["model_version"],
        "note": "Scores are model estimates, not guaranteed probabilities.",
    }


def explain(text: str, top_n: int = 6) -> list[dict]:
    """Which word/character features pushed the score for the top class (for the ML Lab)."""
    m = _load()
    if m is None:
        return []
    pipe = m["pipeline"]
    feats = pipe.named_steps["features"]
    clf = pipe.named_steps["classifier"]
    x = feats.transform([text])
    names = feats.get_feature_names_out()
    cls = int(np.argmax(clf.predict_proba(x)[0]))
    contrib = x.multiply(clf.coef_[cls]).tocsr()
    idx = contrib.indices
    vals = contrib.data
    order = np.argsort(vals)[::-1][:top_n]
    return [{"feature": names[idx[i]].replace("words__", "word: ").replace("chars__", "chars: "),
             "contribution": round(float(vals[i]), 4)} for i in order if vals[i] > 0]


def compare(text: str) -> dict:
    return {"model": predict(text), "keyword_baseline": baseline.predict(text)}


if __name__ == "__main__":
    print(json.dumps(compare(" ".join(sys.argv[1:]) or "My kitchen tap is leaking"), indent=2))
