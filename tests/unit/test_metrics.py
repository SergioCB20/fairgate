import numpy as np
import pytest

from fairgate.metrics import drop_ungrouped, fairness_metric, fairness_metric_with_ci
from fairgate.results import evaluate
from fairgate.schema import Rule

# Grupo a: 4 personas, selección 3/4; grupo b: 4 personas, selección 1/4.
Y_TRUE = np.array([1, 1, 0, 1, 1, 1, 0, 0])
Y_PRED = np.array([1, 1, 1, 0, 1, 0, 0, 0])
G = np.array(["a", "a", "a", "a", "b", "b", "b", "b"])


def test_symmetric_forms():
    assert fairness_metric("spd", Y_TRUE, Y_PRED, G, None) == pytest.approx(0.5)
    assert fairness_metric("di", Y_TRUE, Y_PRED, G, None) == pytest.approx(0.25 / 0.75)
    # TPR a = 2/3, TPR b = 1/2
    assert fairness_metric("eod", Y_TRUE, Y_PRED, G, None) == pytest.approx(2 / 3 - 1 / 2)


def test_directional_di_uses_unprivileged_over_rest():
    assert fairness_metric("di", Y_TRUE, Y_PRED, G, "b") == pytest.approx(0.25 / 0.75)
    # Si el no privilegiado es el más favorecido, el DI supera 1 y la regla ge 0.8 pasa
    assert fairness_metric("di", Y_TRUE, Y_PRED, G, "a") == pytest.approx(3.0)


def test_drop_ungrouped_removes_nan():
    yt, yp, g = drop_ungrouped([1, 0, 1], [1, 1, 0], np.array(["a", np.nan, "b"], dtype=object))
    assert list(g) == ["a", "b"] and list(yt) == [1, 1]


def test_bootstrap_interval_contains_point_estimate():
    rng = np.random.default_rng(1)
    g = np.where(rng.random(1000) < 0.5, "a", "b")
    yt = rng.integers(0, 2, 1000)
    yp = (rng.random(1000) < np.where(g == "a", 0.6, 0.4)).astype(int)
    value, (lo, hi), _ = fairness_metric_with_ci("spd", yt, yp, g, None, 200, 0.95, 0)
    assert lo <= value <= hi


def test_decision_uses_worst_bound():
    rule = Rule(id="R", metric="spd", operator="le", threshold=0.10)
    # Punto por debajo del umbral, pero el extremo superior lo supera -> falla
    res = evaluate(rule, 0.08, ci=(0.05, 0.12))
    assert res.decision_value == 0.12 and not res.passed
    rule_ge = Rule(id="R2", metric="di", operator="ge", threshold=0.80)
    assert evaluate(rule_ge, 0.85, ci=(0.78, 0.9)).decision_value == 0.78
