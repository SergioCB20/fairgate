"""Métricas de equidad de grupo (SPD, EOD, DI) y su intervalo de confianza por bootstrap.

Formas (Cap. 4, Contrato C3):
- Direccional, si el contrato declara el grupo no privilegiado u: se compara u contra el
  resto de los grupos (agrupados como privilegiados).
      SPD = |P(h=1|u) - P(h=1|p)|,  EOD = |TPR(u) - TPR(p)|,  DI = P(h=1|u) / P(h=1|p)
- Simétrica, si no se conoce u: SPD y EOD = max_g - min_g; DI = min_g / max_g.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

GROUP_METRICS = ("spd", "eod", "di")


def _rate(mask: np.ndarray, y_pred: np.ndarray) -> float:
    n = mask.sum()
    return float(y_pred[mask].mean()) if n else float("nan")


def group_rates(y_true: np.ndarray, y_pred: np.ndarray, groups: np.ndarray, unprivileged: str | None):
    """Tasa de selección y TPR por grupo (o por u/resto en la forma direccional).

    `groups` debe venir sin filas fuera de grupo (ver `drop_ungrouped`).
    """
    if unprivileged is not None:
        keys = {"u": groups == unprivileged, "p": groups != unprivileged}
    else:
        keys = {str(g): groups == g for g in np.unique(groups)}
    pos = y_true == 1
    sel = {k: _rate(m, y_pred) for k, m in keys.items()}
    tpr = {k: _rate(m & pos, y_pred) for k, m in keys.items()}
    return sel, tpr


def drop_ungrouped(y_true, y_pred, groups):
    """Quita las filas que no pertenecen a ningún grupo declarado y normaliza los grupos a str."""
    groups = np.asarray(groups, dtype=object)
    valid = np.array([g is not None and not (isinstance(g, float) and np.isnan(g)) for g in groups])
    return (
        np.asarray(y_true)[valid],
        np.asarray(y_pred)[valid],
        groups[valid].astype(str),
    )


def fairness_metric(
    name: str, y_true: np.ndarray, y_pred: np.ndarray, groups: np.ndarray, unprivileged: str | None
) -> float:
    sel, tpr = group_rates(y_true, y_pred, groups, unprivileged)
    if unprivileged is not None:
        if name == "spd":
            return abs(sel["u"] - sel["p"])
        if name == "eod":
            return abs(tpr["u"] - tpr["p"])
        if name == "di":
            return sel["u"] / sel["p"] if sel["p"] > 0 else float("nan")
    else:
        s, t = np.array(list(sel.values())), np.array(list(tpr.values()))
        if name == "spd":
            return float(np.nanmax(s) - np.nanmin(s))
        if name == "eod":
            return float(np.nanmax(t) - np.nanmin(t))
        if name == "di":
            return float(np.nanmin(s) / np.nanmax(s)) if np.nanmax(s) > 0 else float("nan")
    raise ValueError(f"Métrica de grupo desconocida: {name}")


def bootstrap_ci(
    statistic: Callable[[np.ndarray], float],
    n: int,
    n_resamples: int,
    confidence: float,
    random_state: int,
) -> tuple[float, float]:
    """Intervalo percentil: statistic recibe los índices remuestreados (Efron & Tibshirani, 1993)."""
    rng = np.random.default_rng(random_state)
    values = np.empty(n_resamples)
    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        with np.errstate(divide="ignore", invalid="ignore"):
            values[i] = statistic(idx)
    alpha = (1 - confidence) / 2
    return float(np.nanquantile(values, alpha)), float(np.nanquantile(values, 1 - alpha))


def fairness_metric_with_ci(
    name: str,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    groups: np.ndarray,
    unprivileged: str | None,
    n_resamples: int,
    confidence: float,
    random_state: int,
):
    value = fairness_metric(name, y_true, y_pred, groups, unprivileged)
    ci = bootstrap_ci(
        lambda idx: fairness_metric(name, y_true[idx], y_pred[idx], groups[idx], unprivileged),
        n=len(y_true),
        n_resamples=n_resamples,
        confidence=confidence,
        random_state=random_state,
    )
    sel, tpr = group_rates(y_true, y_pred, groups, unprivileged)
    return value, ci, {"selection_rate": sel, "tpr": tpr}
