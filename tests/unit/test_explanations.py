"""Generador de razones de rechazo (Zona 3) y su estabilidad (Cap. 6, 6.4)."""
import numpy as np
import pandas as pd
import pytest

from fairgate.explanations import contributions, rejection_reasons, top_k_agreement
from fairgate.preprocessing import build_model_pipeline
from fairgate.schema import FeatureSpec, ModelSpec

from .conftest import synthetic_frame

FEATURES = FeatureSpec(numeric=["x1"], categorical=["c1"])


def _fit(estimator="logistic_regression", n=1500):
    df = synthetic_frame(n=n)
    model = build_model_pipeline(FEATURES, ModelSpec(estimator=estimator))
    x = df[["x1", "c1"]]
    model.fit(x, df["y"])
    return model, x


def test_contributions_are_per_source_variable_and_additive():
    model, x = _fit()
    ref = x.iloc[:400]  # menos que el tamaño del fondo: se usa completo
    contrib = contributions(model, x.iloc[:50], ref, favorable_label=1)
    assert list(contrib.columns) == ["x1", "c1"]  # las columnas one-hot de c1 vuelven a c1
    # Modelo lineal: la suma de contribuciones es el logit menos el logit medio de la referencia.
    clf, pre = model[-1], model[:-1]
    expected = clf.decision_function(pre.transform(x.iloc[:50])) - clf.decision_function(pre.transform(ref)).mean()
    np.testing.assert_allclose(contrib.sum(axis=1).to_numpy(), expected, atol=1e-6)


def test_contributions_follow_the_favorable_label():
    model, x = _fit()
    a = contributions(model, x.iloc[:20], x, favorable_label=1)
    b = contributions(model, x.iloc[:20], x, favorable_label=0)
    np.testing.assert_allclose(a.to_numpy(), -b.to_numpy())


@pytest.mark.parametrize("estimator", ["logistic_regression", "hist_gradient_boosting", "random_forest"])
def test_reasons_only_for_rejections_and_most_negative_first(estimator):
    model, x = _fit(estimator)
    batch = x.iloc[:300].set_axis([f"id{i}" for i in range(300)])
    decisions = pd.Series((model.predict(batch) == 1).astype(int), index=batch.index)
    reasons = rejection_reasons(model, batch, x, decisions, favorable_label=1, top_k=2)

    rejected = set(decisions[decisions == 0].index)
    assert rejected and set(reasons["pseudo_id"]) <= rejected
    assert (reasons["contribution"] < 0).all()  # solo empujan hacia el rechazo
    assert reasons["rank"].between(1, 2).all()
    for _, r in reasons.groupby("pseudo_id"):
        assert list(r["rank"]) == list(range(1, len(r) + 1))
        assert r["contribution"].is_monotonic_increasing  # la más negativa primero


def test_no_reasons_when_nobody_is_rejected():
    model, x = _fit()
    batch = x.iloc[:10]
    reasons = rejection_reasons(model, batch, x, pd.Series(1, index=batch.index), favorable_label=1)
    assert reasons.empty


def test_top_k_agreement():
    a = pd.DataFrame({"pseudo_id": ["u", "u", "v", "v", "w"], "feature": ["x1", "c1", "x1", "c1", "x1"]})
    b = pd.DataFrame({"pseudo_id": ["u", "u", "v", "v"], "feature": ["c1", "x1", "x1", "p"]})
    s = top_k_agreement(a, b)
    assert s["applicants"] == 2  # w solo lo rechaza el primer modelo
    assert s["identical"] == 0.5  # u coincide (sin importar el orden); v no
    assert s["overlap"] == pytest.approx((1 + 1 / 3) / 2)
