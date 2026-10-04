"""Canal de linaje: registra cada ejecución de compuerta en MLflow (Cap. 4, Canal de Linaje).

Cada ejecución padre tiene un rol: `pipeline` (compuertas C1 a C3 sobre el lote versionado) u
`operacion` (Contrato C4 sobre los lotes de producción puntuados por un modelo aprobado). La
Zona 4 lee estas ejecuciones para construir el grafo RDF.
"""
from __future__ import annotations

import math
import os
import re
import tempfile
from pathlib import Path

from .data import PROJECT_ROOT
from .results import GateResult

DEFAULT_TRACKING_URI = f"sqlite:///{(PROJECT_ROOT / 'mlflow.db').as_posix()}"


def enabled() -> bool:
    return os.environ.get("FAIRGATE_LINEAGE", "1") != "0"


def tracking_uri_default() -> str:
    return os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)


def experiment_name(dataset: str) -> str:
    return f"fairgate-{dataset}"


def _clean(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\-. /]", "_", name)


class Lineage:
    def __init__(
        self,
        dataset: str,
        batch_hash: str,
        n_records: int,
        tracking_uri: str | None = None,
        role: str = "pipeline",
        tags: dict[str, str] | None = None,
    ):
        import mlflow

        self.mlflow = mlflow
        self.role = role
        mlflow.set_tracking_uri(tracking_uri or tracking_uri_default())
        mlflow.set_experiment(experiment_name(dataset))
        self.parent = mlflow.start_run(run_name=f"{role}-{batch_hash[:8]}")
        mlflow.set_tags({
            "fairgate.dataset": dataset,
            "fairgate.batch_hash": batch_hash,
            "fairgate.records_count": str(n_records),
            "fairgate.role": role,
            **(tags or {}),
        })

    @property
    def run_id(self) -> str:
        return self.parent.info.run_id

    def log_gate(self, result: GateResult, model=None, register_as: str | None = None) -> str:
        mlflow = self.mlflow
        with mlflow.start_run(run_name=f"{result.contract_id}-{result.subject}", nested=True) as run:
            mlflow.log_params({
                "contract_id": result.contract_id,
                "contract_version": result.contract_version,
                "gate": result.gate,
                "subject": result.subject,
                "batch_hash": result.batch_hash,
            })
            mlflow.set_tags({
                "fairgate.gate_passed": str(result.passed),
                "fairgate.started_at": result.started_at,
                "fairgate.role": "gate",
            })
            for r in result.rules:
                if not r.applicable:
                    continue
                base = _clean(r.key.replace("[", ".").replace("]", ""))
                for suffix, v in (("value", r.value), ("ci_low", r.ci_low), ("ci_high", r.ci_high)):
                    if v is not None and not math.isnan(v):
                        mlflow.log_metric(f"{base}.{suffix}", v)
                mlflow.log_metric(f"{base}.passed", float(r.passed))
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "gate_result.json"
                p.write_text(result.to_json(), encoding="utf-8")
                mlflow.log_artifact(str(p))
            if model is not None:
                import mlflow.sklearn

                # MLflow 3 serializa con skops (formato seguro): se declaran los tipos permitidos.
                mlflow.sklearn.log_model(
                    model,
                    name="model",
                    registered_model_name=register_as,
                    skops_trusted_types=["numpy.dtype"],
                )
            return run.info.run_id

    def close(self, passed: bool) -> None:
        self.mlflow.set_tag(f"fairgate.{self.role}_passed", str(passed))
        self.mlflow.end_run()
