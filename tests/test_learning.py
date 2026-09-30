import numpy as np

from openphoto.learning import fit_ranker


def test_ranker_requires_independent_shoots_and_no_implicit_negatives():
    model, status = fit_ranker([], {}, {}, None)
    assert model is None and not status["promoted"]


def test_ranker_promotes_only_on_held_out_improvement():
    analyses, shoots, pairs = {}, {}, []
    rng = np.random.default_rng(8)
    for shoot in range(4):
        for pair in range(12):
            a, b = f"{shoot}-a-{pair}", f"{shoot}-b-{pair}"
            analyses[a] = {"features": [0.9, float(rng.random())], "score": 0.48}
            analyses[b] = {"features": [0.1, float(rng.random())], "score": 0.52}
            shoots[a] = shoots[b] = str(shoot)
            pairs.append((a, b))
    model, status = fit_ranker(pairs, analyses, shoots)
    assert status["validation"] == "fixed-shoot-holdout"
    assert status["promoted"] and model is not None
    assert status["accuracy"] > 0.9 and status["baseline"] == 0
    assert not set(model["training_shoots"]) & set(model["validation_shoots"])
    candidate, comparison = fit_ranker(pairs, analyses, shoots, previous={**model, "accuracy": 0})
    assert comparison["incumbent_accuracy"] > 0.9
    assert not set(candidate["training_shoots"]) & set(candidate["validation_shoots"])
