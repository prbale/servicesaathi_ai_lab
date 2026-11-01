"""ML pipeline checks: real training, leakage-free splits, honest metrics, low-confidence handling."""
import json

import pytest

from app.services.ml import baseline, classifier, dataset, train


@pytest.fixture(scope="module")
def report():
    r = train.train()
    classifier.reload()
    return r


def test_dataset_has_enough_examples_per_category():
    rows = dataset.load()
    for label in dataset.LABELS:
        assert sum(r["label"] == label for r in rows) >= 60
    assert any(r["kind"] == "out_of_scope" for r in rows) and any(r["kind"] == "ambiguous" for r in rows)


def test_splits_keep_template_groups_together():
    rows = [r for r in dataset.load() if r["kind"] == "in_scope"]
    tr, va, te = train.split_by_group(rows, (0.6, 0.2, 0.2))
    g = [{r["group"] for r in s} for s in (tr, va, te)]
    assert not (g[0] & g[1]) and not (g[0] & g[2]) and not (g[1] & g[2])
    assert len(tr) + len(va) + len(te) == len(rows)


def test_report_contains_required_metrics(report):
    for who in ("model", "keyword_baseline"):
        m = report["test"][who]
        assert {"accuracy", "macro_f1", "per_category", "confusion_matrix"} <= set(m)
        for lab in dataset.LABELS:
            assert {"precision", "recall"} <= set(m["per_category"][lab])
    assert report["dataset_version"].startswith("ds-") and report["model_version"]
    assert report["threshold"] > 1 / 3, "a threshold <= 1/3 would never ask the user"
    json.dumps(report)  # serialisable


def test_model_beats_chance_by_a_wide_margin(report):
    # Honest floor, not a target: chance is ~0.33 for three balanced classes.
    assert report["test"]["model"]["accuracy"] > 0.6


def test_prediction_shape_and_low_confidence_returns_none(report):
    p = classifier.predict("My kitchen tap is leaking")
    assert p["top_category"] == "plumbing" and set(p["scores"]) == set(dataset.LABELS)
    assert abs(sum(p["scores"].values()) - 1) < 1e-3
    vague = classifier.predict("hello")
    if vague["top_score"] < vague["threshold"]:
        assert vague["category"] is None and vague["confident"] is False


def test_keyword_baseline_abstains_without_keywords():
    assert baseline.predict("book me a haircut")["category"] is None
    assert baseline.predict("the switch is sparking")["category"] == "electrical"
