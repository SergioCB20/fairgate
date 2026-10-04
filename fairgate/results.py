"""Resultados estructurados de cada compuerta (Cap. 4, 4.3.1): alimentan el linaje (Zona 4)."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .schema import Contract, Rule

_OPS = {
    "le": lambda v, t: v <= t,
    "ge": lambda v, t: v >= t,
    "lt": lambda v, t: v < t,
    "gt": lambda v, t: v > t,
}


def worst_bound(rule: Rule, value: float, ci_low: float | None, ci_high: float | None) -> float:
    """Extremo del intervalo más desfavorable respecto del umbral (ADR-008)."""
    if ci_low is None or ci_high is None:
        return value
    return ci_high if rule.operator in ("le", "lt") else ci_low


def best_bound(rule: Rule, value: float, ci_low: float | None, ci_high: float | None) -> float:
    """Extremo del intervalo más favorable: la regla falla solo si todo el intervalo la incumple
    (ADR-017, Contrato C4)."""
    if ci_low is None or ci_high is None:
        return value
    return ci_low if rule.operator in ("le", "lt") else ci_high


_DECISION = {"worst_bound": worst_bound, "best_bound": best_bound}


@dataclass
class RuleResult:
    rule_id: str
    metric: str
    attribute: str | None
    value: float
    threshold: float
    operator: str
    severity: str
    passed: bool
    ci_low: float | None = None
    ci_high: float | None = None
    decision_value: float | None = None
    applicable: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.rule_id}[{self.attribute}]" if self.attribute else self.rule_id

    def message(self) -> str:
        ci = (
            f" IC=[{self.ci_low:.4f}, {self.ci_high:.4f}]"
            if self.ci_low is not None and self.ci_high is not None
            else ""
        )
        status = "PASA" if self.passed else "FALLA"
        return (
            f"{self.key}: {self.metric}={self.value:.4f}{ci} "
            f"(decide con {self.decision_value:.4f} {self.operator} {self.threshold}) -> {status}"
        )


def evaluate(
    rule: Rule,
    value: float,
    attribute: str | None = None,
    ci: tuple[float, float] | None = None,
    decide_on: str = "worst_bound",
    details: dict[str, Any] | None = None,
) -> RuleResult:
    ci_low, ci_high = ci if ci is not None else (None, None)
    decision = _DECISION[decide_on](rule, value, ci_low, ci_high) if decide_on in _DECISION else value
    passed = (not math.isnan(decision)) and _OPS[rule.operator](decision, rule.threshold)
    return RuleResult(
        rule_id=rule.id,
        metric=rule.metric,
        attribute=attribute,
        value=float(value),
        threshold=rule.threshold,
        operator=rule.operator,
        severity=rule.severity,
        passed=bool(passed),
        ci_low=None if ci_low is None else float(ci_low),
        ci_high=None if ci_high is None else float(ci_high),
        decision_value=float(decision),
        details=details or {},
    )


def not_applicable(rule: Rule, attribute: str | None = None, reason: str = "") -> RuleResult:
    return RuleResult(
        rule_id=rule.id,
        metric=rule.metric,
        attribute=attribute,
        value=float("nan"),
        threshold=rule.threshold,
        operator=rule.operator,
        severity=rule.severity,
        passed=True,
        decision_value=float("nan"),
        applicable=False,
        details={"reason": reason},
    )


@dataclass
class GateResult:
    contract_id: str
    contract_version: str
    gate: str
    dataset: str
    batch_hash: str
    subject: str  # qué se evaluó: "lote", "paso:<nombre>", "modelo:base", "modelo:remediado"
    rules: list[RuleResult]
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """La compuerta aprueba si se cumplen todas sus reglas 'block'."""
        return all(r.passed for r in self.rules if r.severity == "block" and r.applicable)

    @property
    def blocking_failures(self) -> list[RuleResult]:
        return [r for r in self.rules if r.severity == "block" and r.applicable and not r.passed]

    def find(self, rule_id: str, attribute: str | None) -> RuleResult:
        for r in self.rules:
            if r.rule_id == rule_id and r.attribute == attribute:
                return r
        raise KeyError(f"{self.contract_id}: no hay resultado para {rule_id}[{attribute}].")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["passed"] = self.passed
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)

    @classmethod
    def new(cls, contract: Contract, batch_hash: str, subject: str, rules: list[RuleResult], **extra):
        return cls(
            contract_id=contract.contract_id,
            contract_version=contract.version,
            gate=contract.gate,
            dataset=contract.dataset,
            batch_hash=batch_hash,
            subject=subject,
            rules=rules,
            extra=extra,
        )
