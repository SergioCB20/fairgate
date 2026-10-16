"""Resultado de cada configuración (Tabla 21) a partir de una repetición (6.2.2 y 6.2.3).

- Detección: alguna compuerta activa de la configuración bloquea. En el C3 cuenta el modelo base:
  la remediación es la respuesta de la compuerta, no evita que haya detectado.
- Localización: la primera compuerta que bloquea coincide con la verdad de referencia, con alguna
  de sus reglas entre las que fallan y, en el C2, con el paso señalado (y en E2, con la variable
  inyectada entre las que mejor separan los grupos en ese paso; ídem en E4R con la sustituta de la edad).
- Localización secundaria: en E3 y E4R, si la otra compuerta implicada también señaló lo inyectado.
- Tiempo hasta el bloqueo: suma de la duración de las compuertas activas hasta la primera que
  bloquea; en el C4 se reporta además el número de lotes hasta la primera alerta.
"""
from __future__ import annotations

from .protocol import CONFIG_GATES, GATE_ORDER, GATE_STAGE, Protocol


def intensity_of(record: dict):
    i = record["intensity"]
    return tuple(i) if isinstance(i, list) else i


def gate_blocked(record: dict, gate: str) -> bool:
    g = record["gates"][gate]
    if gate == "C4":
        return any(b["blocked"] for b in g["batches"])
    return bool(g["blocked"])


def _failed_rules(record: dict, gate: str) -> list[dict]:
    g = record["gates"][gate]
    if gate == "C4":
        k = g["first_alert_batch"]
        rules = g["batches"][k - 1]["rules"] if k else []
    else:
        rules = g["rules"]
    return [r for r in rules if r["severity"] == "block" and r["applicable"] and not r["passed"]]


def localized(record: dict, gate: str, proto: Protocol) -> bool:
    exp = proto.expected(record["scenario"], intensity_of(record))
    if exp.gate is None or gate != exp.gate:
        return False
    failed = [r for r in _failed_rules(record, gate) if r["rule_id"] in exp.rules]
    if not failed:
        return False
    if exp.step is None:
        return True
    return _matches_step(record, failed, exp, proto)


def _matches_step(record: dict, failed: list[dict], exp, proto: Protocol) -> bool:
    column = proto.injected_column(record["scenario"])
    for r in failed:
        if r.get("step") != exp.step:
            continue
        if column is None:
            return True
        top = next((s["top"] for s in r.get("by_step", []) if s["step"] == exp.step), [])
        if column in top:
            return True
    return False


def secondary_localized(record: dict, proto: Protocol) -> bool | None:
    """Si la compuerta secundaria (p. ej., el C2 en E3) señaló lo inyectado, sin importar el orden."""
    exp = proto.secondary(record["scenario"])
    if exp is None:
        return None
    rules = record["gates"][exp.gate]["rules"]
    failed = [r for r in rules if r["severity"] == "block" and r["applicable"] and not r["passed"]
              and r["rule_id"] in exp.rules]
    if not failed:
        return False
    return True if exp.step is None else _matches_step(record, failed, exp, proto)


def outcome(record: dict, config: str, proto: Protocol) -> dict:
    active = CONFIG_GATES[config]
    gates = [g for g in GATE_ORDER if g in active]
    first = next((g for g in gates if gate_blocked(record, g)), None)
    seconds = 0.0
    for g in gates:
        if g == "C4":
            c4 = record["gates"]["C4"]
            k = c4["first_alert_batch"] if first == "C4" else len(c4["batches"])
            seconds += sum(b["seconds"] for b in c4["batches"][:k])
        else:
            seconds += record["gates"][g]["seconds"]
        if g == first:
            break
    exp = proto.expected(record["scenario"], intensity_of(record))
    return {
        "detected": first is not None,
        "first_gate": first,
        "stage": GATE_STAGE[first] if first else None,
        "localized": localized(record, first, proto) if first and exp.gate else None,
        "seconds_to_block": round(seconds, 3) if first else None,
        "batches_to_alert": record["gates"]["C4"]["first_alert_batch"] if first == "C4" else None,
        "per_gate": {g: gate_blocked(record, g) for g in gates},
    }


def outcomes(record: dict, proto: Protocol) -> dict[str, dict]:
    return {c: outcome(record, c, proto) for c in CONFIG_GATES}
