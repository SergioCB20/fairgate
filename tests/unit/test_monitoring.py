"""Zona 3 y Contrato C4 con dominios sintéticos: pruebas de deriva, seudonimización, scorer y C4."""
import numpy as np
import pandas as pd
import pytest

from fairgate.engine import Session
from fairgate.monitoring import (
    Monitor,
    ProductionBatch,
    Pseudonymizer,
    column_drift,
    score_batch,
    simulate_batches,
)
from fairgate.results import evaluate
from fairgate.schema import Rule

from .conftest import synthetic_frame, write_domain


def _biased_batch(n=600, seed=7) -> ProductionBatch:
    """Lote de producción donde x1 sube solo para z = 2: el modelo favorece a ese grupo."""
    df = synthetic_frame(n=n, seed=seed)
    df.loc[df["z"] == 2, "x1"] += 1.5
    return ProductionBatch("sesgado", df)


@pytest.fixture
def monitor(tmp_path):
    dom = write_domain(tmp_path, synthetic_frame(n=4000))
    return Monitor.from_session(Session(dom), log_lineage=False)


# --------------------------------------------------------------------------- pruebas de deriva


def test_column_drift_uses_evidently_defaults():
    rng = np.random.default_rng(0)
    big, small = pd.Series(rng.normal(size=3000)), pd.Series(rng.normal(size=500))
    # Con lotes pequeños la distancia de Wasserstein fluctúa cerca de 0,1 aun sin deriva: por eso
    # la deriva de datos solo se registra ('warn'). Aquí se usan lotes grandes para que sea estable.
    same, shifted = pd.Series(rng.normal(size=1500)), pd.Series(rng.normal(1.0, size=400))
    # Referencia de más de 1 000 registros: Wasserstein normalizada y Jensen-Shannon, umbral 0,1
    assert column_drift(big, same, numeric=True) == {**column_drift(big, same, True), "test": "wasserstein", "drift": False}
    assert column_drift(big, shifted, numeric=True)["drift"]
    cats = pd.Series(rng.integers(0, 4, 3000))
    assert column_drift(cats, pd.Series(rng.integers(0, 4, 400)), numeric=False)["test"] == "jensenshannon"
    assert not column_drift(cats, pd.Series(rng.integers(0, 4, 400)), numeric=False)["drift"]
    assert column_drift(cats, pd.Series(np.zeros(400, dtype=int)), numeric=False)["drift"]
    # Referencia menor: Kolmogorov-Smirnov y chi-cuadrado, p < 0,05
    assert column_drift(small, same, numeric=True)["test"] == "ks"
    assert column_drift(small, shifted, numeric=True)["drift"]
    assert column_drift(pd.Series(rng.integers(0, 3, 500)), pd.Series(rng.integers(0, 3, 300)), False)["test"] == "chi2"


def test_best_bound_fails_only_when_whole_interval_violates():
    rule = Rule(id="R", metric="spd", operator="le", threshold=0.10)
    assert evaluate(rule, 0.12, ci=(0.05, 0.20), decide_on="best_bound").passed
    assert not evaluate(rule, 0.12, ci=(0.05, 0.20), decide_on="worst_bound").passed
    assert not evaluate(rule, 0.18, ci=(0.11, 0.25), decide_on="best_bound").passed
    di = Rule(id="D", metric="di", operator="ge", threshold=0.80)
    assert evaluate(di, 0.75, ci=(0.60, 0.85), decide_on="best_bound").passed
    assert not evaluate(di, 0.70, ci=(0.60, 0.78), decide_on="best_bound").passed


def test_rule_level_decision_overrides_the_contract():
    """ADR-018: el C3 bloquea con el valor y advierte con el peor extremo del intervalo."""
    from fairgate.gates import group_fairness_results
    from fairgate.schema import Contract

    contract = Contract.model_validate({
        "contract_id": "C3", "version": "1", "gate": "QA_GATE_3", "stage": "modelo", "dataset": "sint",
        "protected_attributes": [{"name": "z", "groups": [1, 2]}],
        "rules": [{"id": "SPD", "metric": "spd", "operator": "le", "threshold": 0.10},
                  {"id": "SPD-IC", "metric": "spd", "operator": "le", "threshold": 0.10, "severity": "warn",
                   "decide_on": "worst_bound"}],
        "statistics": {"method": "bootstrap", "n_resamples": 200, "decide_on": "point"},
    })
    rng = np.random.default_rng(0)
    groups = pd.DataFrame({"z": np.repeat(["1", "2"], [60, 600])})
    y_pred = np.r_[rng.random(60) < 0.85, rng.random(600) < 0.90].astype(int)  # SPD ≈ 0,05, grupo pequeño
    block, warn = (group_fairness_results(contract, r, np.ones(660, int), y_pred, groups)[0] for r in contract.rules)
    assert block.decision_value == block.value and block.passed
    assert warn.decision_value == warn.ci_high and not warn.passed  # el intervalo cruza el umbral


# --------------------------------------------------------------------------- captura y scoring


def test_pseudonyms_are_keyed_and_scorer_never_sees_protected_attribute(monitor):
    a, b = Pseudonymizer(b"clave"), Pseudonymizer(b"otra")
    assert a("lote", 3) == a("lote", 3) != b("lote", 3)
    assert len(set(a("lote", 100))) == 100 and a("lote", 1) != a("otro", 1)

    seen = []

    class Spy:
        classes_ = monitor.model.classes_

        def predict_proba(self, x):
            seen.append(set(x.columns))
            return monitor.model.predict_proba(x)

        def predict(self, x):
            seen.append(set(x.columns))
            return monitor.model.predict(x)

    batch = simulate_batches(synthetic_frame(n=200), 1)[0]
    scored = score_batch(monitor.domain, monitor.contract, Spy(), batch, a)
    assert all(cols == {"x1", "c1"} for cols in seen)  # solo las variables del modelo
    assert list(scored.protected.columns) == ["z"]  # el atributo va a un almacén separado
    assert scored.decisions.index.equals(scored.protected.index)  # vinculados por el seudónimo


# --------------------------------------------------------------------------- C4


def test_c4_control_batches_raise_no_alert(monitor):
    test = synthetic_frame(n=1200, seed=3)
    outcomes = monitor.run(simulate_batches(test, 2))
    assert [o.result.subject for o in outcomes] == ["lote:lote-01", "lote:lote-02"]
    assert all(o.result.passed for o in outcomes) and not monitor.trigger_ct
    assert all(not o.result.extra["data_drift_alert"] for o in outcomes)


def test_c4_detects_bias_drift_and_triggers_retraining(monitor):
    out = monitor.process(_biased_batch())
    res = out.result
    spd = res.find("C4-SPD", "z")
    assert not spd.passed and spd.ci_low > 0.10  # todo el intervalo incumple
    assert res.extra["bias_drift_alert"] and res.extra["trigger_ct"] and monitor.trigger_ct
    drift = res.find("C4-DRIFT", None)
    assert drift.details["drifted"] == ["x1"] and res.extra["data_drift_alert"]  # se registra (warn)


def test_c4_eod_waits_for_observed_labels(monitor):
    batch = _biased_batch()
    batch.data = batch.data.drop(columns=["y"])  # etiquetas aún no observadas
    res = monitor.process(batch).result
    assert not res.find("C4-EOD", "z").applicable
    assert res.find("C4-SPD", "z").applicable and not res.passed  # SPD no necesita la etiqueta
    assert res.extra["labels_observed"] is False
