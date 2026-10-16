"""Ejecutor de repeticiones (Cap. 6, 6.2.2 y 6.2.4).

Cada repetición ejecuta la arquitectura completa sin detenerse en el primer bloqueo y registra el
resultado de todas las reglas (valor, intervalo, decisión y paso), la utilidad de los modelos y la
duración de cada compuerta. El resultado de cada configuración (B0, B2, P−C1, P−C2, P) se obtiene
después combinando el de sus compuertas (`configs.py`), así que todas se comparan sobre los mismos
datos y semillas. Como se guardan los valores y no solo el resultado, el análisis de
sensibilidad de los umbrales (6.2.5) no requiere volver a ejecutar.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, roc_auc_score

from fairgate.data import Domain, load_batch, load_domain
from fairgate.gates import run_c1, run_c2, run_c3
from fairgate.monitoring import Monitor, ProductionBatch, simulate_batches
from fairgate.results import GateResult, RuleResult

from .protocol import Protocol
from .scenarios import Prepared, e5_batches, prepare, with_seed


def _num(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 6)


def compact_rule(r: RuleResult) -> dict:
    d = {
        "key": r.key, "rule_id": r.rule_id, "attribute": r.attribute, "metric": r.metric,
        "value": _num(r.value), "ci_low": _num(r.ci_low), "ci_high": _num(r.ci_high),
        "decision_value": _num(r.decision_value), "threshold": r.threshold, "operator": r.operator,
        "severity": r.severity, "passed": r.passed, "applicable": r.applicable,
    }
    if "step" in r.details:  # C2: paso señalado y filtración por paso
        d["step"] = r.details["step"]
        d["by_step"] = [{"step": s["step"], "L": s["L"], "top": [p["feature"] for p in s["top_proxies"]]}
                        for s in r.details.get("by_step", [])]
    if r.metric == "drift_share":
        d["drifted"] = r.details.get("drifted", [])
    return d


def gate_summary(res: GateResult, seconds: float) -> dict:
    return {
        "blocked": not res.passed,
        "failed": [r.key for r in res.blocking_failures],
        "rules": [compact_rule(r) for r in res.rules],
        "seconds": round(seconds, 3),
    }


def _utility(model, test: pd.DataFrame, domain: Domain) -> dict:
    ds = domain.dataset
    x = test[ds.features.all]
    y = (test[ds.target] == ds.favorable_label).astype(int).to_numpy()
    fav = list(model.classes_).index(ds.favorable_label)
    proba = model.predict_proba(x)[:, fav]
    pred = (model.predict(x) == ds.favorable_label).astype(int)
    return {"balanced_accuracy": round(float(balanced_accuracy_score(y, pred)), 6),
            "auroc": round(float(roc_auc_score(y, proba)), 6)}


@dataclass
class Repetition:
    """Resultado de una repetición: el registro serializable y los objetos para la auditoría."""

    record: dict
    results: dict[str, list[GateResult]] = field(default_factory=dict)  # compuerta -> resultados
    model_subjects: list[str] = field(default_factory=list)  # sujetos de C3 en orden (base, remediado)
    reasons: list[pd.DataFrame | None] = field(default_factory=list)  # por lote del C4
    prepared: Prepared | None = None
    final_model: object = None


def run_c4(domain: Domain, model, prepared: Prepared, batches: list[ProductionBatch]):
    monitor = Monitor(domain=domain, model=model, reference=prepared.train,
                      training_hash=prepared.batch_hash, log_lineage=False)
    summaries, results, reasons = [], [], []
    for b in batches:
        t0 = time.perf_counter()
        out = monitor.process(b)
        s = gate_summary(out.result, time.perf_counter() - t0)
        s["records"] = len(b.data)
        s["data_drift_alert"] = bool(out.result.extra["data_drift_alert"])
        summaries.append(s)
        results.append(out.result)
        reasons.append(out.scored.reasons)
    first = next((i for i, s in enumerate(summaries, 1) if s["blocked"]), None)
    return {"batches": summaries, "first_alert_batch": first}, results, reasons


def run_development(proto: Protocol, base: Domain, df: pd.DataFrame, scenario: str, intensity, seed: int,
                    estimator: str | None = None) -> Repetition:
    """E0 a E4: C1, C2, C3 (con remediación) y C4 sobre los lotes del conjunto de prueba."""
    domain = with_seed(base, seed, estimator)
    t0 = time.perf_counter()
    prep = prepare(proto, domain, df, scenario, intensity, seed)
    domain = prep.domain
    c = domain.contracts
    rep = Repetition(record={}, prepared=prep)
    gates: dict = {}

    t = time.perf_counter()
    r1 = run_c1(c["QA_GATE_1"], domain, prep.batch, prep.batch_hash)
    gates["C1"] = gate_summary(r1, time.perf_counter() - t)
    t = time.perf_counter()
    r2 = run_c2(c["QA_GATE_2"], domain, prep.train, prep.batch_hash, steps=prep.c2_steps)
    gates["C2"] = gate_summary(r2, time.perf_counter() - t)
    t = time.perf_counter()
    evals = run_c3(c["QA_GATE_3"], domain, prep.train, prep.test, prep.batch_hash)
    seconds = time.perf_counter() - t
    base_ev = evals[0]
    gates["C3"] = gate_summary(base_ev.result, seconds)
    gates["C3"]["utility"] = {"base": _utility(base_ev.model, prep.test, domain)}
    if len(evals) > 1:
        rem = evals[1]
        gates["C3"]["remediation"] = {
            "blocked": not rem.result.passed,
            "failed": [r.key for r in rem.result.blocking_failures],
            "rules": [compact_rule(r) for r in rem.result.rules],
        }
        gates["C3"]["utility"]["remediado"] = _utility(rem.model, prep.test, domain)
    final = evals[-1]
    rep.final_model = final.model
    rep.model_subjects = [e.subject for e in evals]

    batches = simulate_batches(prep.test, proto.default_batches, random_state=seed)
    gates["C4"], r4, rep.reasons = run_c4(domain, final.model, prep, batches)
    gates["C4"]["model_approved"] = final.result.passed

    rep.results = {"C1": [r1], "C2": [r2], "C3": [e.result for e in evals], "C4": r4}
    rep.record = {
        "scenario": scenario, "intensity": intensity, "seed": seed,
        "estimator": domain.dataset.model.estimator, "info": prep.info, "gates": gates,
        "seconds": round(time.perf_counter() - t0, 3),
    }
    return rep


def run_operation(proto: Protocol, e0: Repetition, disparity: float, lot_size: int, seed: int) -> Repetition:
    """E5: el C4 sobre lotes con disparidad inducida, con el modelo y los datos del E0 de la misma
    semilla. Las compuertas C1 a C3 son las del E0 (los mismos datos), para combinar configuraciones."""
    prep, domain = e0.prepared, e0.prepared.domain
    batches, infos = e5_batches(proto, domain, e0.final_model, prep.train, prep.test, disparity, lot_size, seed)
    c4, r4, reasons = run_c4(domain, e0.final_model, prep, batches)
    c4["model_approved"] = e0.record["gates"]["C4"]["model_approved"]
    for s, info in zip(c4["batches"], infos):
        s["injection"] = info
    gates = {g: e0.record["gates"][g] for g in ("C1", "C2", "C3")}
    gates["C4"] = c4
    rep = Repetition(
        record={"scenario": "E5", "intensity": [disparity, lot_size], "seed": seed,
                "estimator": e0.record["estimator"], "info": {}, "gates": gates},
        results={**{g: e0.results[g] for g in ("C1", "C2", "C3")}, "C4": r4},
        model_subjects=e0.model_subjects, reasons=reasons, prepared=prep, final_model=e0.final_model,
    )
    return rep


# --------------------------------------------------------------------------- campaña


def _key(record: dict) -> tuple:
    return record["scenario"], json.dumps(record["intensity"]), record["seed"], record["estimator"]


def done_keys(path: Path) -> set:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        return {_key(json.loads(line)) for line in f if line.strip()}


def campaign(proto: Protocol, seeds: list[int], scenarios: list[str], out: Path, estimator: str | None = None,
             audit: bool = False, log=print) -> int:
    """Ejecuta los escenarios para cada semilla y agrega un registro por línea a `out` (JSONL).
    Las repeticiones ya registradas se omiten, así que una campaña interrumpida se puede reanudar."""
    from .audit import audit_repetition

    base = load_domain(proto.domain)
    df, _ = load_batch(base)
    est = estimator or base.dataset.model.estimator
    out.parent.mkdir(parents=True, exist_ok=True)
    done = done_keys(out)
    written = 0

    def emit(rep: Repetition):
        nonlocal written
        if audit:
            rep.record["audit"] = audit_repetition(proto, rep)
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(rep.record, ensure_ascii=False, default=str) + "\n")
        done.add(_key(rep.record))
        written += 1

    for seed in seeds:
        e0 = None
        # El E5 reutiliza el modelo del E0; solo hace falta si queda algún E5 pendiente de la semilla.
        e5_pending = [i for i in proto.intensities("E5")
                      if ("E5", json.dumps(list(i)), seed, est) not in done] if "E5" in scenarios else []
        for scenario in scenarios:
            if scenario == "E5":
                continue
            for intensity in proto.intensities(scenario):
                pending = (scenario, json.dumps(intensity), seed, est) not in done
                if not pending and not (scenario == "E0" and e5_pending):
                    continue
                rep = run_development(proto, base, df, scenario, intensity, seed, estimator)
                if scenario == "E0":
                    e0 = rep
                if pending:
                    emit(rep)
                log(f"semilla {seed} · {scenario} {intensity} · {rep.record['seconds']} s")
        if e5_pending:
            if e0 is None:
                e0 = run_development(proto, base, df, "E0", None, seed, estimator)
            for intensity in e5_pending:
                emit(run_operation(proto, e0, *intensity, seed))
                log(f"semilla {seed} · E5 {intensity}")
    return written
