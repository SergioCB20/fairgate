"""Esquema declarativo común de los contratos de equidad y de la especificación del dataset.

Todo lo específico de un caso de estudio (columnas, atributos protegidos, umbrales,
técnica de remediación) se declara en YAML y se valida contra estos modelos antes de
ejecutar cualquier compuerta (ADR-004, ADR-013).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Operator = Literal["le", "ge", "lt", "gt"]
Severity = Literal["block", "warn"]
GateName = Literal["QA_GATE_1", "QA_GATE_2", "QA_GATE_3", "QA_GATE_4"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- dataset


class ColumnSpec(_Strict):
    name: str
    dtype: Literal["int", "float", "str"]
    nullable: bool = False
    allowed_values: list[Any] | None = None
    min_value: float | None = None
    max_value: float | None = None


class FeatureSpec(_Strict):
    numeric: list[str] = Field(default_factory=list)
    categorical: list[str] = Field(default_factory=list)

    @property
    def all(self) -> list[str]:
        return [*self.numeric, *self.categorical]


class ExcludedFeature(_Strict):
    name: str
    reason: str


class SplitSpec(_Strict):
    test_size: float = 0.2
    random_state: int = 42


class ModelSpec(_Strict):
    """Clasificador base de la Zona 2, elegido de un catálogo (ver `preprocessing.ESTIMATORS`).

    Todos los estimadores del catálogo aceptan `sample_weight`, que requiere la reponderación.
    """
    estimator: Literal["logistic_regression", "random_forest", "hist_gradient_boosting"] = (
        "logistic_regression"
    )
    params: dict[str, Any] = Field(
        default_factory=dict, description="Hiperparámetros que reemplazan a los valores por defecto."
    )


class DatasetSpec(_Strict):
    name: str
    path: str = Field(description="Ruta del archivo de datos, relativa a la raíz del proyecto.")
    source: str | None = Field(default=None, description="Origen del dataset (p. ej., URL de Kaggle).")
    target: str
    favorable_label: int | str = 1
    columns: list[ColumnSpec]
    leakage_columns: list[str] = Field(default_factory=list)
    features: FeatureSpec
    excluded_features: list[ExcludedFeature] = Field(default_factory=list)
    split: SplitSpec = Field(default_factory=SplitSpec)
    model: ModelSpec = Field(default_factory=ModelSpec)

    @model_validator(mode="after")
    def _features_are_not_target(self) -> "DatasetSpec":
        if self.target in self.features.all:
            raise ValueError(f"La etiqueta '{self.target}' no puede ser una variable del modelo.")
        return self


# --------------------------------------------------------------------------- contrato


class ProtectedAttribute(_Strict):
    name: str
    column: str | None = Field(
        default=None,
        description="Columna de la que se leen los valores; por defecto, 'name'.",
    )
    groups: list[Any] | dict[str, str | list[Any]] = Field(
        description=(
            "Lista de valores (cada valor es un grupo) o diccionario etiqueta -> expresión "
            "sobre el dataset (p. ej. 'Age < 25') o etiqueta -> lista de valores a agrupar."
        )
    )
    unprivileged: Any | None = None
    source_columns: list[str] = Field(default_factory=list)
    use_as_feature: bool = False
    justification: str | None = None

    @property
    def value_column(self) -> str:
        return self.column or self.name

    @property
    def group_labels(self) -> list[str]:
        if isinstance(self.groups, dict):
            return [str(k) for k in self.groups]
        return [str(v) for v in self.groups]

    @property
    def forbidden_columns(self) -> set[str]:
        """Columnas que no pueden ser variables del modelo (ADR-013)."""
        if self.use_as_feature:
            return set()
        return {self.name, self.value_column, *self.source_columns}

    @model_validator(mode="after")
    def _check(self) -> "ProtectedAttribute":
        if self.use_as_feature and not self.justification:
            raise ValueError(
                f"El atributo '{self.name}' declara use_as_feature: true sin justificación."
            )
        if self.unprivileged is not None and str(self.unprivileged) not in self.group_labels:
            raise ValueError(
                f"El grupo no privilegiado '{self.unprivileged}' no es un grupo de '{self.name}'."
            )
        if len(self.group_labels) < 2:
            raise ValueError(f"El atributo '{self.name}' debe tener al menos dos grupos.")
        return self


class Rule(_Strict):
    id: str
    metric: str
    operator: Operator
    threshold: float
    severity: Severity = "block"


class Statistics(_Strict):
    method: Literal["bootstrap", "none"] = "none"
    n_resamples: int = 500
    confidence: float = 0.95
    # worst_bound: se exige evidencia de cumplimiento (C3, antes de desplegar; ADR-008).
    # best_bound: se exige evidencia de incumplimiento (C4, para alertar en la operación; ADR-017).
    decide_on: Literal["worst_bound", "best_bound", "point"] = "worst_bound"
    random_state: int = 42


class Remediation(_Strict):
    enabled: bool = True
    method: str = "reweighing"
    allow_protected_at_inference: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class Contract(_Strict):
    contract_id: str
    version: str
    gate: GateName
    stage: str
    dataset: str
    protected_attributes: list[ProtectedAttribute]
    rules: list[Rule]
    statistics: Statistics = Field(default_factory=Statistics)
    remediation: Remediation | None = None
    tooling: str | None = None
    params: dict[str, Any] = Field(
        default_factory=dict, description="Parámetros propios de la compuerta (p. ej., folds del C2)."
    )

    @model_validator(mode="after")
    def _check(self) -> "Contract":
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.contract_id}: hay identificadores de regla repetidos.")
        if self.remediation is not None and self.gate != "QA_GATE_3":
            raise ValueError(f"{self.contract_id}: solo el Contrato C3 admite remediación.")
        names = [a.name for a in self.protected_attributes]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.contract_id}: hay atributos protegidos repetidos.")
        return self

    @property
    def forbidden_columns(self) -> set[str]:
        cols: set[str] = set()
        for attr in self.protected_attributes:
            cols |= attr.forbidden_columns
        return cols


# --------------------------------------------------------------------------- carga


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_dataset_spec(path: str | Path) -> DatasetSpec:
    return DatasetSpec.model_validate(_read_yaml(Path(path)))


def load_contract(path: str | Path) -> Contract:
    return Contract.model_validate(_read_yaml(Path(path)))
