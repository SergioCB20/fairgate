"""Consolidación de resultados (Cap. 6, 6.3): tablas por escenario, intensidad y configuración,
pruebas pareadas, curvas del C4, compromiso equidad–utilidad, costo, auditabilidad, y el análisis
de sensibilidad y la calibración de umbrales (6.2.5), que se recalculan a partir de los valores
registrados sin volver a ejecutar."""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from .configs import intensity_of, outcomes
from .protocol import CONFIGS, GATE_ORDER, Protocol
from .stats import holm, mcnemar_exact, wilcoxon_paired, wilson


def load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _pct(k: int, n: int) -> str:
    if n == 0:
        return "—"
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({k / n:.0%}) [{lo:.2f}; {hi:.2f}]"


def _med(xs, digits: int = 1):
    xs = [x for x in xs if x is not None]
    return f"{statistics.median(xs):.{digits}f}" if xs else "—"


def _table(header: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return lines


def _groups(records: list[dict]) -> dict[tuple, list[dict]]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        groups[(r["scenario"], json.dumps(r["intensity"]), r["estimator"])].append(r)
    for g in groups.values():
        g.sort(key=lambda r: r["seed"])
    return dict(sorted(groups.items()))


# --------------------------------------------------------------------------- 6.3


def detection_table(records: list[dict], proto: Protocol) -> list[str]:
    rows = []
    for (scenario, intensity, est), recs in _groups(records).items():
        outs = [outcomes(r, proto) for r in recs]
        exp = proto.expected(scenario, intensity_of(recs[0]))
        for c in CONFIGS:
            o = [x[c] for x in outs]
            det = [x for x in o if x["detected"]]
            loc = [x for x in det if x["localized"]] if exp.gate else []
            stages = [x["stage"] for x in det]
            rows.append([
                scenario, intensity, est, exp.gate or "ninguna", c,
                _pct(len(det), len(o)),
                _pct(len(loc), len(det)) if exp.gate else "—",
                max(set(stages), key=stages.count) if stages else "—",
                _med([x["seconds_to_block"] for x in det]),
                _med([x["batches_to_alert"] for x in det]),
            ])
    return _table(["Escenario", "Intensidad", "Clasificador", "Esperada", "Config.", "Detección [IC 95 %]",
                   "Localización [IC 95 %]", "Etapa (moda)", "s hasta el bloqueo (mediana)",
                   "Lotes hasta la alerta (mediana)"], rows)


def false_positive_table(records: list[dict], proto: Protocol) -> list[str]:
    lines = []
    e0 = [r for r in records if r["scenario"] == "E0"]
    if e0:
        rows = []
        for c in CONFIGS:
            o = [outcomes(r, proto)[c] for r in e0]
            rows.append([c, _pct(sum(x["detected"] for x in o), len(o))])
        lines += _table(["Configuración", "Falsos positivos en E0"], rows) + [""]
        rows = [[g, _pct(sum(_blocked(r, g) for r in e0), len(e0))] for g in GATE_ORDER]
        lines += _table(["Compuerta", "Falsos positivos en E0"], rows) + [""]
    control = [r for r in records if r["scenario"] == "E5" and r["intensity"][0] == 0]
    if control:
        by_lot = defaultdict(list)
        for r in control:
            by_lot[r["intensity"][1]] += [b["blocked"] for b in r["gates"]["C4"]["batches"]]
        rows = [[n, _pct(sum(v), len(v))] for n, v in sorted(by_lot.items())]
        lines += _table(["Tamaño del lote", "Falsos positivos del C4 por lote (E5, disparidad 0)"], rows)
    return lines


def _blocked(record: dict, gate: str) -> bool:
    g = record["gates"][gate]
    return any(b["blocked"] for b in g["batches"]) if gate == "C4" else g["blocked"]


def confirmatory(scenario: str, intensity, proto: Protocol) -> bool:
    """Comparaciones confirmatorias (6.2.4): la intensidad más severa de cada escenario de inyección
    (en E1, la menor proporción) y, en E5, la mayor disparidad con el tamaño de lote del contrato
    (435). El resto es descriptivo."""
    if scenario == "E0":
        return False
    if scenario == "E5":
        return tuple(intensity) == (max(proto.e5_disparity), 435)
    return intensity == proto.strongest(scenario)


def paired_tests(records: list[dict], proto: Protocol) -> list[str]:
    """McNemar exacta (detección y localización) y Wilcoxon (tiempo) de P frente a cada configuración.
    La corrección de Holm se aplica, por métrica, al conjunto de comparaciones confirmatorias; las
    demás se reportan sin ajustar, como descriptivas."""
    raw = {"deteccion": {}, "localizacion": {}, "tiempo": {}}
    detail = {}
    for (scenario, intensity, est), recs in _groups(records).items():
        if scenario == "E0":
            continue
        exp = proto.expected(scenario, intensity_of(recs[0]))
        outs = [outcomes(r, proto) for r in recs]
        conf = confirmatory(scenario, intensity_of(recs[0]), proto)
        for c in CONFIGS:
            if c == "P":
                continue
            key = f"{scenario} {intensity} {est} P vs {c}"
            raw["deteccion"][key] = mcnemar_exact([o["P"]["detected"] for o in outs], [o[c]["detected"] for o in outs])
            if exp.gate:
                raw["localizacion"][key] = mcnemar_exact([bool(o["P"]["localized"]) for o in outs],
                                                         [bool(o[c]["localized"]) for o in outs])
            raw["tiempo"][key] = wilcoxon_paired([o["P"]["seconds_to_block"] for o in outs],
                                                 [o[c]["seconds_to_block"] for o in outs])
            detail[key] = (scenario, intensity, est, c, conf)
    lines = []
    for metric, tests in raw.items():
        if not tests:
            continue
        adj = holm({k: v["p"] for k, v in tests.items() if detail[k][4]})
        rows = []
        for k, v in sorted(tests.items(), key=lambda kv: not detail[kv[0]][4]):
            s, i, e, c, conf = detail[k]
            extra = f"{v['only_a']} / {v['only_b']}" if "only_a" in v else f"n = {v['n']}"
            rows.append([s, i, e, c, "confirmatoria" if conf else "descriptiva", extra, f"{v['p']:.4f}",
                         f"{adj[k]:.4f}" if conf else "—"])
        head = "Solo P / solo la otra" if metric != "tiempo" else "Pares"
        title = {"deteccion": "Detección", "localizacion": "Localización", "tiempo": "Tiempo hasta el bloqueo"}[metric]
        lines += [f"**{title}: P frente a cada configuración**", ""]
        lines += _table(["Escenario", "Intensidad", "Clasificador", "Frente a", "Tipo", head, "p", "p (Holm)"],
                        rows) + [""]
    return lines


def secondary_table(records: list[dict], proto: Protocol) -> list[str]:
    """Localización secundaria (E3: C2-INC en la imputación; E4R: el C3 detecta el daño), y en E4R el
    resultado de la remediación."""
    from .configs import secondary_localized

    rows = []
    for (scenario, intensity, est), recs in _groups(records).items():
        exp = proto.secondary(scenario)
        if exp is None:
            continue
        hits = [secondary_localized(r, proto) for r in recs]
        rem = [r["gates"]["C3"].get("remediation") for r in recs]
        applied = [x for x in rem if x]
        rows.append([scenario, intensity, est, f"{exp.gate} {'/'.join(exp.rules)}" + (f" en {exp.step}" if exp.step else ""),
                     _pct(sum(bool(h) for h in hits), len(hits)),
                     _pct(sum(not x["blocked"] for x in applied), len(applied)) if applied else "—"])
    if not rows:
        return []
    return _table(["Escenario", "Intensidad", "Clasificador", "Localización secundaria", "Señalada [IC 95 %]",
                   "Remediado cumple el C3 [IC 95 %]"], rows)


def c4_grid(records: list[dict], target: float = 0.8) -> list[str]:
    """E5: detección por lote según la disparidad y el tamaño del lote, y lote mínimo para `target`."""
    cells = defaultdict(list)
    for r in records:
        if r["scenario"] == "E5":
            d, n = r["intensity"]
            cells[(r["estimator"], d, n)] += [b["blocked"] for b in r["gates"]["C4"]["batches"]]
    if not cells:
        return []
    rows, minimum = [], {}
    for (est, d, n), v in sorted(cells.items()):
        rate = sum(v) / len(v)
        rows.append([est, d, n, _pct(sum(v), len(v))])
        if d > 0 and rate >= target and (est, d) not in minimum:
            minimum[(est, d)] = n
    lines = _table(["Clasificador", "Disparidad inducida", "Tamaño del lote", "Lotes con alerta [IC 95 %]"], rows)
    lines += ["", f"Lote mínimo con detección ≥ {target:.0%}: "
              + ("; ".join(f"{est}, disparidad {d}: {n}" for (est, d), n in sorted(minimum.items())) or "ninguno")]
    return lines


def remediation_tradeoff(records: list[dict]) -> list[str]:
    """E4 (y cualquier escenario con remediación): ΔEquidad y ΔUtilidad entre el modelo base y el remediado."""
    cells = defaultdict(list)
    for r in records:
        c3 = r["gates"]["C3"]
        if "remediation" not in c3 or r["scenario"] == "E5":  # el E5 repite el C3 del E0 de su semilla
            continue
        base = {x["key"]: x["value"] for x in c3["rules"] if x["applicable"]}
        rem = {x["key"]: x["value"] for x in c3["remediation"]["rules"] if x["applicable"]}
        u = c3["utility"]
        d = {k: rem[k] - base[k] for k in base if k in rem and base[k] is not None and rem[k] is not None}
        d["balanced_accuracy"] = u["remediado"]["balanced_accuracy"] - u["base"]["balanced_accuracy"]
        d["auroc"] = u["remediado"]["auroc"] - u["base"]["auroc"]
        d["remediado_aprueba"] = float(not c3["remediation"]["blocked"])
        cells[(r["scenario"], json.dumps(r["intensity"]), r["estimator"])].append(d)
    if not cells:
        return ["Ninguna repetición activó la remediación."]
    keys = sorted({k for v in cells.values() for d in v for k in d})
    rows = [[s, i, e, len(v)] + [_med([d.get(k) for d in v], 3) if k != "remediado_aprueba"
                                 else f"{sum(d[k] for d in v):.0f}/{len(v)}" for k in keys]
            for (s, i, e), v in sorted(cells.items())]
    return _table(["Escenario", "Intensidad", "Clasificador", "n"] + [f"Δ {k}" for k in keys], rows) + [
        "", "Δ = remediado − base (medianas). En SPD y EOD, negativo es mejor; en DI, positivo; "
            "`remediado_aprueba` cuenta las repeticiones en que el modelo remediado cumple el C3."]


def cost_table(records: list[dict]) -> list[str]:
    rows = []
    for g in GATE_ORDER:
        if g == "C4":
            xs = [b["seconds"] for r in records for b in r["gates"]["C4"]["batches"]]
            rows.append(["C4 (por lote)", _med(xs)])
        else:
            rows.append([g, _med([r["gates"][g]["seconds"] for r in records if r["scenario"] != "E5"])])
    rows.append(["Repetición completa (E0–E4)", _med([r.get("seconds") for r in records])])
    triples = [r["audit"]["triples"] for r in records if "audit" in r]
    if triples:
        rows.append(["Tripletas del grafo por repetición", _med(triples)])
    return _table(["Componente", "Mediana (s, salvo tripletas)"], rows)


def audit_table(records: list[dict]) -> list[str]:
    audited = [r for r in records if "audit" in r]
    if not audited:
        return ["Sin auditoría registrada (ejecutar la campaña con --auditoria)."]
    rows = [["Conformidad SHACL", _pct(sum(r["audit"]["conforms"] for r in audited), len(audited))]]
    for pc in ("PC1", "PC2", "PC3", "PC4", "PC5"):
        rows.append([f"Fidelidad de la {pc}", _pct(sum(r["audit"]["fidelity"][pc] for r in audited), len(audited))])
    exp = [r for r in audited if r["audit"]["expected"] is not None]
    rows.append(["Respuesta esperada según la Tabla 20", _pct(sum(r["audit"]["expected"] for r in exp), len(exp))])
    return _table(["Verificación", "Repeticiones que la cumplen [IC 95 %]"], rows)


# --------------------------------------------------------------------------- 6.2.5


def c2_sensitivity(records: list[dict], proto: Protocol, auc=(0.55, 0.60, 0.65, 0.70),
                   inc=(0.01, 0.02, 0.03, 0.05)) -> list[str]:
    """Detección (E2, E3) y falsos positivos (E0) del C2 con otros umbrales, a partir de L por paso."""
    def series(r):  # L de cada paso, por atributo protegido
        return {x["attribute"]: [s["L"] for s in x["by_step"]]
                for x in r["gates"]["C2"]["rules"] if x["rule_id"] == "C2-AUC"}

    def blocked(r, t_auc, t_inc):
        for ls in series(r).values():
            if max(ls) > t_auc or any(b - a > t_inc for a, b in zip(ls, ls[1:])):
                return True
        return False

    rows = []
    for (scenario, intensity, est), recs in _groups(records).items():
        if scenario not in ("E0", "E2", "E3"):
            continue
        for ta in auc:
            for ti in inc:
                k = sum(blocked(r, ta, ti) for r in recs)
                rows.append([scenario, intensity, est, ta, ti, _pct(k, len(recs))])
    return _table(["Escenario", "Intensidad", "Clasificador", "C2-AUC", "C2-INC",
                   "Bloquea el C2 [IC 95 %]"], rows)


def c4_drift_calibration(records: list[dict], thresholds=(0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.60),
                         max_fp: float = 0.05, lot_sizes=(218, 435, 871, 1742)) -> list[str]:
    """Calibración del umbral de `C4-DRIFT` (proporción de variables con deriva) con E0 y E5: falsos
    positivos en los lotes de control y detección en los lotes con disparidad, por tamaño de lote.
    Criterio propuesto (a validar): el menor umbral con falsos positivos ≤ `max_fp` en todos los
    tamaños de lote."""
    shares = defaultdict(list)
    for r in records:
        if r["scenario"] == "E5":
            d, n = r["intensity"]
        elif r["scenario"] == "E0":
            d, n = 0.0, None
        else:
            continue
        for b in r["gates"]["C4"]["batches"]:
            share = next(x["value"] for x in b["rules"] if x["metric"] == "drift_share")
            nominal = n or min(lot_sizes, key=lambda s: abs(s - b["records"]))  # E0: 435 o 436 → 435
            shares[(d, nominal)].append(share)
    if not shares:
        return []
    rows, ok = [], []
    for t in thresholds:
        fps = []
        for (d, n), v in sorted(shares.items()):
            k = sum(s > t for s in v)
            rows.append([t, d, n, _pct(k, len(v))])
            if d == 0:
                fps.append(k / len(v))
        if fps and max(fps) <= max_fp:
            ok.append(t)
    lines = _table(["Umbral", "Disparidad inducida", "Tamaño del lote", "Lotes con deriva de datos [IC 95 %]"], rows)
    lines += ["", f"Umbral propuesto (menor con falsos positivos ≤ {max_fp:.0%} en todos los tamaños): "
              + (str(min(ok)) if ok else "ninguno de la grilla")]
    return lines


def report(records: list[dict], proto: Protocol, title: str) -> str:
    sections = [
        ("## Detección, localización, etapa y tiempo (6.3)", detection_table(records, proto)),
        ("## Falsos positivos", false_positive_table(records, proto)),
        ("## Localización secundaria y remediación", secondary_table(records, proto)),
        ("## Pruebas pareadas (6.2.4)", paired_tests(records, proto)),
        ("## C4: detección según la disparidad y el tamaño del lote", c4_grid(records)),
        ("## Compromiso entre equidad y utilidad (remediación)", remediation_tradeoff(records)),
        ("## Costo computacional", cost_table(records)),
        ("## Auditabilidad (6.4)", audit_table(records)),
        ("## Sensibilidad del C2 (6.2.5)", c2_sensitivity(records, proto)),
        ("## Calibración del umbral de deriva del C4 (6.2.5)", c4_drift_calibration(records)),
    ]
    out = [f"# {title}", "", f"Registros: {len(records)}.", ""]
    for head, body in sections:
        out += [head, ""] + (body or ["Sin datos."]) + [""]
    return "\n".join(out)
