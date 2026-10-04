"""Catálogo de técnicas de remediación del Contrato C3 (ADR-012).

Cada técnica declara si necesita el atributo protegido al predecir. El motor rechaza las
que lo necesitan salvo que el contrato declare `allow_protected_at_inference: true`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.pipeline import Pipeline


class RemediationNotAllowed(Exception):
    """La técnica declarada usa el atributo protegido en la inferencia y el contrato no lo admite."""


@dataclass(frozen=True)
class RemediationTechnique:
    name: str
    uses_protected_at_inference: bool
    apply: Callable[..., tuple[Pipeline, dict]]
    reference: str


def reweighing_weights(groups: pd.Series, y: pd.Series) -> tuple[np.ndarray, dict]:
    """Pesos W(g, y) = P(g) P(y) / P(g, y) (Kamiran & Calders, 2012, sección 5.2).

    `groups` es la combinación de los grupos de todos los atributos protegidos.
    """
    df = pd.DataFrame({"g": groups.astype(str).values, "y": y.values})
    n = len(df)
    p_g = df["g"].value_counts() / n
    p_y = df["y"].value_counts() / n
    p_gy = df.groupby(["g", "y"]).size() / n
    table = {
        (g, yv): float(p_g[g] * p_y[yv] / p_gy[(g, yv)]) for (g, yv) in p_gy.index
    }
    weights = np.array([table[(g, yv)] for g, yv in zip(df["g"], df["y"])])
    cell_sizes = (p_gy * n).astype(int).to_dict()
    report = {
        "weights": {f"{g}|y={yv}": w for (g, yv), w in table.items()},
        "cell_sizes": {f"{g}|y={yv}": c for (g, yv), c in cell_sizes.items()},
        "max_weight": float(max(table.values())),
    }
    return weights, report


def _apply_reweighing(base: Pipeline, x_train: pd.DataFrame, y_train: pd.Series, groups: pd.Series, **_):
    weights, report = reweighing_weights(groups, y_train)
    model = clone(base)
    model.fit(x_train, y_train, classifier__sample_weight=weights)
    return model, report


CATALOG: dict[str, RemediationTechnique] = {
    "reweighing": RemediationTechnique(
        name="reweighing",
        uses_protected_at_inference=False,
        apply=_apply_reweighing,
        reference="Kamiran & Calders (2012)",
    ),
}


def get_technique(method: str, allow_protected_at_inference: bool) -> RemediationTechnique:
    if method not in CATALOG:
        raise ValueError(f"Técnica de remediación desconocida: '{method}'. Disponibles: {sorted(CATALOG)}")
    tech = CATALOG[method]
    if tech.uses_protected_at_inference and not allow_protected_at_inference:
        raise RemediationNotAllowed(
            f"'{method}' necesita el atributo protegido al predecir; el contrato debe declarar "
            "allow_protected_at_inference: true para usarla."
        )
    return tech
