"""Pairwise preference learning with shoot-level validation and explicit promotion."""

from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler


def vector(analysis):
    values = list(analysis["features"])
    values.extend(analysis.get("embedding") or [0] * 512)
    return np.asarray(values, np.float64)


def fit_ranker(pairs, analyses, shoot_ids, previous=None):
    import hashlib

    valid = [(a, b) for a, b in pairs if a in analyses and b in analyses and shoot_ids[a] == shoot_ids[b]]
    groups = sorted({shoot_ids[a] for a, _ in valid})
    status = {"comparisons": len(valid), "shoots": len(groups), "promoted": False}
    if len(valid) < 30 or len(groups) < 3:
        return previous, {
            **status,
            "message": "Нужны минимум 30 явных сравнений из 3 съёмок для независимой проверки",
        }

    if previous and "training_shoots" not in previous:
        previous = {**previous, "training_shoots": groups, "validation_shoots": []}
        return previous, {
            **status,
            "message": "У прежней модели нет истории обучения. Нужна новая независимая съёмка для сравнения.",
        }
    trained = set(previous.get("training_shoots", [])) if previous else set()
    held_out = set(previous.get("validation_shoots", [])) if previous else set()
    held_out.intersection_update(groups)
    held_out.difference_update(trained)
    if not held_out:
        available = [group for group in groups if group not in trained]
        if not available:
            return previous, {**status, "message": "Нужна съёмка, на которой прежняя модель не обучалась."}
        held_out = {min(available, key=lambda group: hashlib.sha256(group.encode()).hexdigest())}
    training = [(a, b) for a, b in valid if shoot_ids[a] not in held_out]
    validation = [(a, b) for a, b in valid if shoot_ids[a] in held_out]
    if len(training) < 20 or len(validation) < 10 or len({shoot_ids[a] for a, b in training}) < 2:
        return previous, {
            **status,
            "message": "Нужны 20 обучающих сравнений из двух съёмок и 10 независимых проверочных сравнений.",
        }
    model = _fit(training, analyses)
    accuracy = sum(score(analyses[a], model) > score(analyses[b], model) for a, b in validation) / len(
        validation
    )
    baseline = sum(analyses[a]["score"] > analyses[b]["score"] for a, b in validation) / len(validation)
    incumbent = (
        sum(score(analyses[a], previous) > score(analyses[b], previous) for a, b in validation)
        / len(validation)
        if previous
        else baseline
    )
    status.update(
        accuracy=accuracy,
        baseline=baseline,
        incumbent_accuracy=incumbent,
        validation="fixed-shoot-holdout",
        validation_shoots=sorted(held_out),
    )
    if accuracy >= max(0.6, baseline + 0.05) and accuracy >= incumbent:
        model.update(
            accuracy=accuracy,
            comparisons=len(training),
            version=2,
            feature_version="analysis-v2",
            training_shoots=sorted({shoot_ids[a] for a, b in training}),
            validation_shoots=sorted(held_out),
            training_pairs=[list(pair) for pair in training],
            training_digest=hashlib.sha256(repr(sorted(training)).encode()).hexdigest(),
        )
        return model, {**status, "promoted": True, "message": "Модель улучшила отбор на отложенных съёмках"}
    return previous, {**status, "message": "Улучшение не подтверждено; предыдущий отбор сохранён"}


def _fit(pairs, analyses):
    differences = np.asarray([vector(analyses[a]) - vector(analyses[b]) for a, b in pairs])
    x = np.concatenate([differences, -differences])
    y = np.r_[np.ones(len(differences)), np.zeros(len(differences))]
    scaler = StandardScaler(with_mean=False).fit(x)
    classifier = LogisticRegression(C=0.05, fit_intercept=False, max_iter=500).fit(scaler.transform(x), y)
    return {"weights": classifier.coef_[0].tolist(), "scale": scaler.scale_.tolist()}


def score(analysis, model):
    if not model:
        return analysis["score"]
    raw = np.dot(vector(analysis) / np.asarray(model["scale"]), np.asarray(model["weights"]))
    # Taste stays a bounded correction. This number is not a liking probability.
    return float(analysis["score"] + 0.15 * np.tanh(raw / 2))
