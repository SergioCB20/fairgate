"""Estadística del protocolo (Cap. 6, 6.2.4): intervalos de Wilson, McNemar exacta, Wilcoxon de
rangos con signo y corrección de Holm. Solo usa SciPy."""
from __future__ import annotations

import math

from scipy import stats


def wilson(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción k/n."""
    if n == 0:
        return float("nan"), float("nan")
    z = stats.norm.ppf(1 - (1 - confidence) / 2)
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def mcnemar_exact(a: list[bool], b: list[bool]) -> dict:
    """Prueba exacta de McNemar sobre resultados pareados: binomial sobre los pares discordantes."""
    if len(a) != len(b):
        raise ValueError("Las dos listas deben estar pareadas.")
    only_a = sum(1 for x, y in zip(a, b) if x and not y)
    only_b = sum(1 for x, y in zip(a, b) if y and not x)
    n = only_a + only_b
    p = 1.0 if n == 0 else float(stats.binomtest(only_a, n, 0.5).pvalue)
    return {"only_a": only_a, "only_b": only_b, "p": p}


def wilcoxon_paired(a: list[float], b: list[float]) -> dict:
    """Rangos con signo de Wilcoxon sobre pares completos (sin valores faltantes)."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    diffs = [x - y for x, y in pairs if x != y]
    if len(diffs) < 1:
        return {"n": len(pairs), "p": 1.0}
    return {"n": len(pairs), "p": float(stats.wilcoxon([x for x, _ in pairs], [y for _, y in pairs]).pvalue)}


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    """Valores p ajustados por el método de Holm (monótonos y acotados en 1)."""
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(ordered)
    adjusted, running = {}, 0.0
    for i, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - i) * p))
        adjusted[name] = running
    return adjusted
