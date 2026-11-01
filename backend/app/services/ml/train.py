"""Train, evaluate and save the service-category classifier.

    python -m app.services.ml.train

Pipeline: TF-IDF (word 1–2 grams + character 3–5 grams) → logistic regression.
Steps:
  1. Load data/ml/service_requests.jsonl and compute its version hash.
  2. Split IN-SCOPE examples by template group: 60% train / 20% validation / 20% test.
     Out-of-scope and ambiguous examples are split by group into validation / test only.
  3. Pick regularisation C on validation macro-F1.
  4. Pick the low-confidence threshold on validation (see choose_threshold).
  5. Report held-out test metrics for the model AND the keyword baseline.
  6. Save preprocessing + classifier together in one joblib file, plus a JSON report.
"""
import json
import random
import time
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.pipeline import FeatureUnion, Pipeline

from ...config import get_settings
from . import baseline
from .dataset import LABELS, dataset_version, load

SEED = 13
MODEL_FAMILY = "tfidf-logreg-v1"


def artifact_paths() -> tuple[Path, Path]:
    d = Path(get_settings().model_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / "classifier.joblib", d / "classifier_report.json"


def split_by_group(rows: list[dict], fractions: tuple[float, ...], seed: int = SEED) -> list[list[dict]]:
    """Assign whole template groups to splits so paraphrases never straddle splits."""
    by_label: dict[str, list[str]] = {}
    for r in rows:
        by_label.setdefault(r["label"], [])
        if r["group"] not in by_label[r["label"]]:
            by_label[r["label"]].append(r["group"])
    rng = random.Random(seed)
    assignment: dict[str, int] = {}
    for groups in by_label.values():  # stratify: split each label's groups separately
        groups = sorted(groups)
        rng.shuffle(groups)
        cuts = np.cumsum([round(f * len(groups)) for f in fractions[:-1]])
        for i, g in enumerate(groups):
            assignment[g] = int(np.searchsorted(cuts, i, side="right"))
    out: list[list[dict]] = [[] for _ in fractions]
    for r in rows:
        out[assignment[r["group"]]].append(r)
    return out


def build_pipeline(c: float) -> Pipeline:
    features = FeatureUnion([
        ("words", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, lowercase=True)),
        ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, lowercase=True)),
    ])
    clf = LogisticRegression(C=c, max_iter=2000, random_state=SEED)
    return Pipeline([("features", features), ("classifier", clf)])


def classification_metrics(y_true: list[str], y_pred: list[str | None]) -> dict:
    """Metrics on in-scope rows. A None prediction ('asked the user') counts as wrong here."""
    pred = [p if p is not None else "__none__" for p in y_pred]
    p, r, f, s = precision_recall_fscore_support(y_true, pred, labels=LABELS, zero_division=0)
    return {
        "n": len(y_true),
        "accuracy": round(accuracy_score(y_true, pred), 4),
        "macro_f1": round(f1_score(y_true, pred, labels=LABELS, average="macro", zero_division=0), 4),
        "per_category": {lab: {"precision": round(p[i], 4), "recall": round(r[i], 4), "f1": round(f[i], 4),
                               "support": int(s[i])} for i, lab in enumerate(LABELS)},
        "confusion_matrix": {"labels": LABELS + ["(no prediction)"],
                             "rows_true": LABELS,
                             "matrix": confusion_matrix(y_true, pred, labels=LABELS + ["__none__"])[:3].tolist()},
    }


def decision(top_score: float, threshold: float) -> bool:
    return top_score >= threshold


def choose_threshold(pipe: Pipeline, val_rows: list[dict]) -> dict:
    """Utility-based threshold choice on validation data.

    Accepting a correct guess +1; accepting a WRONG guess -2 (silently booking the wrong
    trade is costly); asking the user on an in-scope request -0.5 (mild friction);
    accepting an out-of-scope request -1; asking on out-of-scope +1.
    Ambiguous rows: accepting any acceptable label 0, wrong -1, asking +0.5.
    """
    probs = pipe.predict_proba([r["text"] for r in val_rows])
    classes = list(pipe.classes_)
    # Start above 1/3: with three classes the top score is always >= 0.34, so lower
    # thresholds would mean "never ask" and the search would be meaningless.
    grid = [round(x, 2) for x in np.arange(0.40, 0.91, 0.02)]
    table = []
    for t in grid:
        u = 0.0
        for row, pr in zip(val_rows, probs):
            top = classes[int(np.argmax(pr))]
            accept = decision(float(np.max(pr)), t)
            if row["kind"] == "in_scope":
                u += (1 if top == row["label"] else -2) if accept else -0.5
            elif row["kind"] == "out_of_scope":
                u += -1 if accept else 1
            else:
                u += (0 if top in row["acceptable"] else -1) if accept else 0.5
        table.append({"threshold": t, "utility": round(u, 2)})
    best = max(table, key=lambda x: (x["utility"], -x["threshold"]))
    return {"chosen": best["threshold"], "utility_curve": table}


def selective_report(pipe: Pipeline, rows: list[dict], threshold: float) -> dict:
    probs = pipe.predict_proba([r["text"] for r in rows]) if rows else []
    classes = list(pipe.classes_)
    out = {"in_scope": {"n": 0, "accepted": 0, "accepted_correct": 0},
           "out_of_scope": {"n": 0, "asked_user": 0, "examples": []},
           "ambiguous": {"n": 0, "asked_user": 0, "accepted_acceptable": 0, "accepted_wrong": 0, "examples": []}}
    for row, pr in zip(rows, probs):
        top, score = classes[int(np.argmax(pr))], float(np.max(pr))
        accept = decision(score, threshold)
        if row["kind"] == "in_scope":
            o = out["in_scope"]
            o["n"] += 1
            o["accepted"] += int(accept)
            o["accepted_correct"] += int(accept and top == row["label"])
        elif row["kind"] == "out_of_scope":
            o = out["out_of_scope"]
            o["n"] += 1
            o["asked_user"] += int(not accept)
            o["examples"].append({"text": row["text"], "top": top, "score": round(score, 3), "asked_user": not accept})
        else:
            o = out["ambiguous"]
            o["n"] += 1
            o["asked_user"] += int(not accept)
            o["accepted_acceptable"] += int(accept and top in row["acceptable"])
            o["accepted_wrong"] += int(accept and top not in row["acceptable"])
            o["examples"].append({"text": row["text"], "top": top, "score": round(score, 3), "asked_user": not accept,
                                  "acceptable": row["acceptable"]})
    i = out["in_scope"]
    i["coverage"] = round(i["accepted"] / i["n"], 4) if i["n"] else None
    i["selective_accuracy"] = round(i["accepted_correct"] / i["accepted"], 4) if i["accepted"] else None
    return out


def train() -> dict:
    rows = load()
    ds_version = dataset_version(rows)
    in_scope = [r for r in rows if r["kind"] == "in_scope"]
    other = [r for r in rows if r["kind"] != "in_scope"]
    train_rows, val_in, test_in = split_by_group(in_scope, (0.6, 0.2, 0.2))
    val_other, test_other = split_by_group(other, (0.5, 0.5))
    assert not ({r["group"] for r in train_rows} & {r["group"] for r in test_in}), "group leakage"

    X_tr, y_tr = [r["text"] for r in train_rows], [r["label"] for r in train_rows]
    # 1) choose C on validation macro-F1 (in-scope only)
    c_scores = []
    for c in (0.5, 1, 2, 5, 10, 20):
        pipe = build_pipeline(c).fit(X_tr, y_tr)
        f1 = f1_score([r["label"] for r in val_in], pipe.predict([r["text"] for r in val_in]), average="macro")
        c_scores.append({"C": c, "val_macro_f1": round(f1, 4)})
    best_c = max(c_scores, key=lambda x: (x["val_macro_f1"], -x["C"]))["C"]
    pipe = build_pipeline(best_c).fit(X_tr, y_tr)

    # 2) threshold on validation (in-scope + out-of-scope + ambiguous)
    thr = choose_threshold(pipe, val_in + val_other)
    threshold = thr["chosen"]

    # 3) held-out test metrics
    y_test = [r["label"] for r in test_in]
    raw_pred = list(pipe.predict([r["text"] for r in test_in]))
    base_pred = [baseline.predict(r["text"])["category"] for r in test_in]
    model_version = f"{MODEL_FAMILY}+{ds_version}+C{best_c}"

    report = {
        "model_version": model_version,
        "dataset_version": ds_version,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sklearn_version": sklearn.__version__,
        "pipeline": "TF-IDF(word 1-2 + char_wb 3-5) -> LogisticRegression",
        "split_sizes": {"train": len(train_rows), "validation_in_scope": len(val_in), "test_in_scope": len(test_in),
                        "validation_other": len(val_other), "test_other": len(test_other)},
        "groups": {"train": len({r['group'] for r in train_rows}), "test": len({r['group'] for r in test_in})},
        "hyperparameter_search": c_scores,
        "chosen_C": best_c,
        "threshold": threshold,
        "threshold_search": thr["utility_curve"],
        "test": {
            "model": classification_metrics(y_test, raw_pred),
            "keyword_baseline": classification_metrics(y_test, base_pred),
            "model_with_threshold": selective_report(pipe, test_in + test_other, threshold),
        },
        "caveats": [
            "The dataset is synthetic and template-generated. These scores do not prove real-world accuracy.",
            "Scores from predict_proba are model estimates, not calibrated probabilities.",
            "The baseline's 'no prediction' (no keyword or a tie) is counted as an error in its accuracy.",
            "The baseline keywords were written by the same author who wrote the templates, so the "
            "baseline comparison is optimistic for the baseline.",
            "The test set has few template groups per class, so metrics have high variance "
            "(compare validation vs test scores).",
        ],
    }
    model_path, report_path = artifact_paths()
    joblib.dump({"pipeline": pipe, "threshold": threshold, "labels": LABELS, "model_version": model_version,
                 "dataset_version": ds_version, "sklearn_version": sklearn.__version__}, model_path)
    report_path.write_text(json.dumps(report, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    return report


if __name__ == "__main__":
    r = train()
    m, b = r["test"]["model"], r["test"]["keyword_baseline"]
    sel = r["test"]["model_with_threshold"]
    print(f"model {r['model_version']}")
    print(f"splits {r['split_sizes']}")
    print(f"test accuracy  model={m['accuracy']}  baseline={b['accuracy']}")
    print(f"test macro-F1  model={m['macro_f1']}  baseline={b['macro_f1']}")
    print(f"threshold {r['threshold']}  in-scope coverage={sel['in_scope']['coverage']} "
          f"selective acc={sel['in_scope']['selective_accuracy']}  "
          f"out-of-scope asked={sel['out_of_scope']['asked_user']}/{sel['out_of_scope']['n']}  "
          f"ambiguous asked={sel['ambiguous']['asked_user']}/{sel['ambiguous']['n']}")
