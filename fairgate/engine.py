"""Motor de contratos: ejecuta las compuertas de un dominio en orden y detiene el flujo
ante la primera violación de una regla 'block' (Cap. 4, mecanismo de interrupción).

El C4 no se ejecuta aquí: es un invariante de operación (`monitoring.py`)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import lineage
from .data import Domain, load_batch, load_domain, split
from .gates import ModelEvaluation, check_contract, run_c1, run_c2, run_c3
from .results import GateResult


class DataNotAvailable(Exception):
    pass


@dataclass
class GateOutcome:
    gate: str
    results: list[GateResult]  # C3 puede tener dos: modelo base y remediado
    models: list[ModelEvaluation] = field(default_factory=list)

    @property
    def final(self) -> GateResult:
        return self.results[-1]

    @property
    def passed(self) -> bool:
        return self.final.passed


class Session:
    """Ejecución del pipeline de compuertas sobre un lote. Los resultados se calculan una vez."""

    def __init__(self, domain: Domain | str | Path, log_lineage: bool | None = None):
        self.domain = domain if isinstance(domain, Domain) else load_domain(domain)
        for c in self.domain.contracts.values():
            check_contract(c, self.domain.dataset)
        self.log_lineage = lineage.enabled() if log_lineage is None else log_lineage
        self._outcomes: dict[str, GateOutcome] = {}
        self._df: pd.DataFrame | None = None
        self._lineage: lineage.Lineage | None = None
        self.pipeline_run_id: str | None = None  # ejecución padre en MLflow
        self.run_ids: dict[str, str] = {}  # sujeto evaluado -> ejecución de su compuerta en MLflow

    # ------------------------------------------------------------------ datos
    def _load(self) -> None:
        if self._df is not None:
            return
        if not self.domain.data_available:
            raise DataNotAvailable(
                f"No se encontró {self.domain.data_path}. Ver README (obtención del dataset)."
            )
        self._df, self.batch_hash = load_batch(self.domain)
        self.train, self.test = split(self.domain, self._df)
        if self.log_lineage:
            self._lineage = lineage.Lineage(self.domain.dataset.name, self.batch_hash, len(self._df))
            self.pipeline_run_id = self._lineage.run_id

    # ------------------------------------------------------------------ compuertas
    def outcome(self, gate: str) -> GateOutcome:
        if gate in self._outcomes:
            return self._outcomes[gate]
        self._load()
        contract = self.domain.contracts[gate]
        if gate == "QA_GATE_1":
            out = GateOutcome(gate, [run_c1(contract, self.domain, self._df, self.batch_hash)])
        elif gate == "QA_GATE_2":
            out = GateOutcome(gate, [run_c2(contract, self.domain, self.train, self.batch_hash)])
        elif gate == "QA_GATE_3":
            evals = run_c3(contract, self.domain, self.train, self.test, self.batch_hash)
            out = GateOutcome(gate, [e.result for e in evals], models=evals)
        elif gate == "QA_GATE_4":
            raise ValueError(
                "El C4 se evalúa en la operación, sobre cada lote de producción: use "
                "fairgate.monitoring.Monitor o `python -m fairgate monitor <dominio>`."
            )
        else:
            raise ValueError(f"Compuerta desconocida: {gate}")
        self._outcomes[gate] = out
        self._log(out)
        return out

    def _log(self, out: GateOutcome) -> None:
        if self._lineage is None:
            return
        if out.models:
            for ev in out.models:
                approved = ev.result.passed and ev is out.models[-1]
                name = f"{self.domain.dataset.name}-scoring" if approved else None
                self.run_ids[ev.subject] = self._lineage.log_gate(ev.result, model=ev.model, register_as=name)
        else:
            for r in out.results:
                self.run_ids[r.subject] = self._lineage.log_gate(r)

    def approved_model(self) -> ModelEvaluation | None:
        """Modelo que el C3 aprobó para el despliegue (Trigger CD), o None si bloqueó."""
        out = self.outcome("QA_GATE_3")
        return out.models[-1] if out.passed else None

    def run(self, stop_on_block: bool = True) -> list[GateOutcome]:
        """Ejecuta las compuertas del desarrollo (C1 a C3) en orden; se detiene en la primera que
        bloquea. El C4 no forma parte del pipeline: se evalúa en la operación (`monitoring`)."""
        done = []
        for contract in self.domain.contracts_in_order():
            if contract.gate == "QA_GATE_4":
                continue
            out = self.outcome(contract.gate)
            done.append(out)
            if stop_on_block and not out.passed:
                break
        self.close()
        return done

    def blocked_before(self, gate: str) -> str | None:
        """Devuelve la compuerta anterior que bloqueó, si la hay."""
        for contract in self.domain.contracts_in_order():
            if contract.gate in (gate, "QA_GATE_4"):
                return None
            if not self.outcome(contract.gate).passed:
                return contract.gate
        return None

    def close(self) -> None:
        if self._lineage is not None:
            self._lineage.close(all(o.passed for o in self._outcomes.values()))
            self._lineage = None
