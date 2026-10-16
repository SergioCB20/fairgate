"""Escenario E6 (Cap. 6, Tabla 20): deriva real con HMDA.

El desarrollo (C1 a C3, con remediación) usa el año de referencia; el C4 procesa los lotes del año
siguiente con el modelo final. Como en E0 a E5, la repetición ejecuta todas las compuertas sin
detenerse en el primer bloqueo, de modo que la respuesta del C4 se mide aunque una compuerta del
desarrollo haya bloqueado. No hay verdad de referencia de localización (deriva no controlada): como
control, el mismo modelo procesa lotes del conjunto de prueba del año de referencia, sin deriva por
construcción. Cada semilla cambia la partición de entrenamiento y prueba del año de referencia.
"""
from __future__ import annotations

import json
import statistics
import time
from collections import Counter
from pathlib import Path

from fairgate.data import load_batch, load_domain, split
from fairgate.gates import run_c1, run_c2, run_c3
from fairgate.monitoring import read_batch, simulate_batches

from .analysis import _pct, _table
from .hmda import production_lots
from .runner import _utility, compact_rule, gate_summary, run_c4
from .scenarios import Prepared, with_seed

DOMAIN = "domains/hmda"


def run_e6(seed: int, estimator: str | None = None, lots: list[Path] | None = None) -> dict:
    base = load_domain(DOMAIN)
    domain = with_seed(base, seed, estimator)
    t0 = time.perf_counter()
    df, batch_hash = load_batch(domain)
    train, test = split(domain, df)
    prep = Prepared(domain=domain, batch=df, train=train, test=test, batch_hash=batch_hash)
    c = domain.contracts
    gates: dict = {}

    t = time.perf_counter()
    gates["C1"] = gate_summary(run_c1(c["QA_GATE_1"], domain, df, batch_hash), time.perf_counter() - t)
    t = time.perf_counter()
    gates["C2"] = gate_summary(run_c2(c["QA_GATE_2"], domain, train, batch_hash), time.perf_counter() - t)
    t = time.perf_counter()
    evals = run_c3(c["QA_GATE_3"], domain, train, test, batch_hash)
    gates["C3"] = gate_summary(evals[0].result, time.perf_counter() - t)
    gates["C3"]["utility"] = {"base": _utility(evals[0].model, test, domain)}
    if len(evals) > 1:
        rem = evals[1]
        gates["C3"]["remediation"] = {"blocked": not rem.result.passed,
                                      "failed": [r.key for r in rem.result.blocking_failures],
                                      "rules": [compact_rule(r) for r in rem.result.rules]}
        gates["C3"]["utility"]["remediado"] = _utility(rem.model, test, domain)
    final = evals[-1]

    production = [read_batch(p, domain) for p in (lots or production_lots())]
    gates["C4"], _, _ = run_c4(domain, final.model, prep, production)
    gates["C4"]["model_approved"] = final.result.passed
    control = simulate_batches(test, len(production), random_state=seed)
    gates["C4_control"], _, _ = run_c4(domain, final.model, prep, control)
    return {"scenario": "E6", "intensity": None, "seed": seed, "estimator": domain.dataset.model.estimator,
            "info": {"reference_rows": len(df), "production_rows": sum(len(b.data) for b in production)},
            "gates": gates, "seconds": round(time.perf_counter() - t0, 3)}


def campaign(seeds: list[int], out: Path, estimator: str | None = None, log=print) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = {(r["seed"], r["estimator"]) for r in map(json.loads, out.read_text(encoding="utf-8").splitlines()) if r}
    est = estimator or load_domain(DOMAIN).dataset.model.estimator
    written = 0
    for seed in seeds:
        if (seed, est) in done:
            continue
        rec = run_e6(seed, estimator)
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        written += 1
        log(f"semilla {seed} · E6 · {rec['seconds']} s")
    return written


# --------------------------------------------------------------------------- reporte


def _med(xs, d=3):
    xs = [x for x in xs if x is not None]
    return f"{statistics.median(xs):.{d}f}" if xs else "—"


def _rule_values(rules: list[dict], prefix: str) -> dict[str, float]:
    return {r["key"]: r["value"] for r in rules if r["key"].startswith(prefix) and r["applicable"]}


def report(records: list[dict]) -> str:
    n = len(records)
    est = records[0]["estimator"] if records else "—"
    lines = [f"# Resultados del E6 (HMDA): {est}", "", f"Repeticiones: {n}.", "", "## Desarrollo (año de referencia)", ""]
    rows = []
    for g in ("C1", "C2", "C3"):
        blocked = [r["gates"][g]["blocked"] for r in records]
        failed = Counter(k for r in records for k in r["gates"][g]["failed"])
        rows.append([g, _pct(sum(blocked), n), ", ".join(f"{k} ({v})" for k, v in failed.most_common()) or "—"])
    rem = [r for r in records if "remediation" in r["gates"]["C3"]]
    rows.append(["C3 remediado", _pct(sum(r["gates"]["C3"]["remediation"]["blocked"] for r in rem), len(rem)) if rem else "—",
                 ", ".join(f"{k} ({v})" for k, v in Counter(k for r in rem for k in r["gates"]["C3"]["remediation"]["failed"]).most_common()) or "—"])
    lines += _table(["Compuerta", "Bloquea [IC 95 %]", "Reglas que bloquean (repeticiones)"], rows)

    keys = sorted({k for r in records for k in _rule_values(r["gates"]["C2"]["rules"], "C2-AUC")})
    lines += ["", "Filtración del C2 en la entrada (mediana) y variables que más la explican:", ""]
    rows = []
    for k in keys:
        vals = [_rule_values(r["gates"]["C2"]["rules"], "C2-AUC").get(k) for r in records]
        tops = Counter(tuple(next(x for x in r["gates"]["C2"]["rules"] if x["key"] == k)["by_step"][0]["top"][:3]) for r in records)
        rows.append([k, _med(vals), " · ".join(tops.most_common(1)[0][0])])
    lines += _table(["Regla", "L", "Tres primeras variables (más frecuente)"], rows)

    lines += ["", "Métricas del C3 (mediana del valor; modelo base y remediado):", ""]
    rows = []
    for k in sorted({k for r in records for k in _rule_values(r["gates"]["C3"]["rules"], "C3-") if "-IC" not in k and "ACC" not in k}):
        b = [_rule_values(r["gates"]["C3"]["rules"], "C3-").get(k) for r in records]
        m = [_rule_values(r["gates"]["C3"]["remediation"]["rules"], "C3-").get(k) for r in rem]
        rows.append([k, _med(b), _med(m)])
    lines += _table(["Regla", "Base", "Remediado"], rows)
    ub = [r["gates"]["C3"]["utility"]["base"]["balanced_accuracy"] for r in records]
    ur = [r["gates"]["C3"]["utility"]["remediado"]["balanced_accuracy"] for r in rem]
    lines += ["", f"Exactitud balanceada: base {_med(ub)}; remediado {_med(ur)}."]

    for gate, title in (("C4", "Operación: lotes del año siguiente (deriva real)"),
                        ("C4_control", "Control: lotes de la prueba del año de referencia")):
        batches = [b for r in records for b in r["gates"][gate]["batches"]]
        nb = len(batches)
        drift = sum(b["data_drift_alert"] for b in batches)
        bias = sum(b["blocked"] for b in batches)
        drifted = Counter(v for b in batches for x in b["rules"] if x["metric"] == "drift_share" for v in x.get("drifted", []))
        failed = Counter(k for b in batches for k in b["failed"])
        share = [next(x["value"] for x in b["rules"] if x["metric"] == "drift_share") for b in batches]
        lines += ["", f"## {title}", "",
                  f"Lotes: {nb} (mediana de {_med([b['records'] for b in batches], 0)} registros).", ""]
        lines += _table(["Indicador", "Valor"], [
            ["Lotes con alerta de deriva de datos (warn)", _pct(drift, nb)],
            ["Proporción de variables con deriva (mediana)", _med(share)],
            ["Lotes con alerta de deriva del sesgo (Trigger CT)", _pct(bias, nb)],
            ["Variables con deriva (lotes)", ", ".join(f"{k} ({v})" for k, v in drifted.most_common()) or "—"],
            ["Reglas que alertan (lotes)", ", ".join(f"{k} ({v})" for k, v in failed.most_common()) or "—"],
        ])
        vals = {}
        for b in batches:
            for x in b["rules"]:
                if x["metric"] in ("spd", "eod", "di") and x["applicable"]:
                    vals.setdefault(x["key"], []).append(x["value"])
        lines += ["", "Métricas por lote (mediana):", ""]
        lines += _table(["Regla", "Mediana"], [[k, _med(v)] for k, v in sorted(vals.items())])
    secs = [r["seconds"] for r in records]
    c2 = [r["gates"]["C2"]["seconds"] for r in records]
    lines += ["", f"Duración por repetición (mediana): {_med(secs, 1)} s; C2: {_med(c2, 1)} s."]
    return "\n".join(lines) + "\n"
