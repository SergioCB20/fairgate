"""Compuertas sobre el caso Davronov: una prueba por cada combinación de regla y atributo
protegido (Cap. 4, mecanismo de interrupción). Se omiten si el dataset no está disponible.

C1 a C3 se evalúan en el pipeline; el C4, en la operación simulada (lotes del conjunto de
prueba, sin deriva inyectada): es el escenario de control, en el que no debe haber alertas."""
from __future__ import annotations

import warnings

import pytest

from fairgate.data import load_domain
from fairgate.engine import Session
from fairgate.gates import expected_cases
from fairgate.monitoring import Monitor, simulate_batches

DOMAIN = load_domain("domains/davronov")
CASES = [
    pytest.param(c.gate, rule_id, attr, id=f"{c.contract_id}:{rule_id}" + (f"[{attr}]" if attr else ""))
    for c in DOMAIN.contracts_in_order()
    if c.gate != "QA_GATE_4"
    for rule_id, attr in expected_cases(c)
]
C4 = DOMAIN.contracts["QA_GATE_4"]
C4_CASES = [
    pytest.param(rule_id, attr, id=f"C4:{rule_id}" + (f"[{attr}]" if attr else ""))
    for rule_id, attr in expected_cases(C4)
]

pytestmark = pytest.mark.skipif(
    not DOMAIN.data_available, reason=f"Dataset no disponible en {DOMAIN.data_path} (ver README)."
)


@pytest.fixture(scope="module")  # se cierra (y cierra su ejecución de MLflow) al terminar el módulo
def session():
    s = Session(DOMAIN)
    yield s
    s.close()


@pytest.mark.parametrize("gate,rule_id,attr", CASES)
def test_rule(session, gate, rule_id, attr):
    blocked = session.blocked_before(gate)
    if blocked:
        pytest.fail(f"No se evalúa: {blocked} bloqueó el pipeline antes de {gate}.")
    result = session.outcome(gate).final
    r = result.find(rule_id, attr)
    print(f"\n{result.subject}: {r.message()}" if r.applicable else f"\n{r.key}: no aplica")
    if r.severity == "warn":
        if r.applicable and not r.passed:
            warnings.warn(r.message())
        return
    assert r.passed, r.message() + (f" · paso: {r.details['step']}" if "step" in r.details else "")


@pytest.fixture(scope="module")
def operation(session):
    """Despliega el modelo aprobado por el C3 y evalúa los lotes simulados con el C4."""
    blocked = session.blocked_before("QA_GATE_4") or (None if session.outcome("QA_GATE_3").passed else "QA_GATE_3")
    if blocked:
        pytest.fail(f"No hay modelo desplegado: {blocked} bloqueó el pipeline.")
    monitor = Monitor.from_session(session)
    batches = simulate_batches(session.test, int(C4.params.get("batches", 4)), DOMAIN.dataset.split.random_state)
    return monitor.run(batches)


@pytest.mark.parametrize("rule_id,attr", C4_CASES)
def test_c4_rule(operation, rule_id, attr):
    failures = []
    for out in operation:
        r = out.result.find(rule_id, attr)
        print(f"\n{out.result.subject}: {r.message()}" if r.applicable else f"\n{r.key}: no aplica")
        if r.applicable and not r.passed:
            failures.append(f"{out.result.subject}: {r.message()}")
    if failures and r.severity == "warn":
        for f in failures:
            warnings.warn(f)
        return
    assert not failures, "Alerta en el escenario de control: " + "; ".join(failures)
