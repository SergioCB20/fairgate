"""Generador de razones de rechazo (Zona 3, Cap. 4, Figura 7).

Para cada solicitante rechazado, las variables con mayor contribución negativa al resultado
favorable según SHAP. Se denominan **factores principales** de la decisión: describen cuánto
aportó cada variable a la puntuación del modelo, no relaciones causales (Cap. 6, 6.4).

Las contribuciones se calculan sobre las variables transformadas y se suman por variable de
origen (p. ej., todas las columnas one-hot de `Region` vuelven a `Region`), lo que conserva la
aditividad de SHAP. Explicador: lineal para la regresión logística y de árboles para los
clasificadores de árboles del catálogo (`preprocessing.ESTIMATORS`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

BACKGROUND_SIZE = 500  # registros de referencia para el explicador lineal


def _output_sources(preprocessing) -> list[str]:
    """Variable de origen de cada columna que produce el ColumnTransformer, en orden."""
    sources: list[str] = []
    for _, transformer, cols in preprocessing.transformers_:
        if transformer == "drop" or not len(cols):
            continue
        last = transformer[-1] if isinstance(transformer, Pipeline) else transformer
        if hasattr(last, "categories_"):  # codificación one-hot: una columna por categoría
            for col, cats in zip(cols, last.categories_):
                sources += [col] * len(cats)
        else:
            sources += list(cols)
    return sources


def _shap_values(classifier, xt: np.ndarray, background: np.ndarray) -> tuple[np.ndarray, int | None]:
    """Contribuciones SHAP y, si el explicador las da por clase, el eje de clases."""
    import shap

    if hasattr(classifier, "coef_"):
        # Con una matriz como fondo, SHAP submuestrea 100 registros; se fija el fondo completo.
        masker = shap.maskers.Independent(background, max_samples=len(background))
        return np.asarray(shap.LinearExplainer(classifier, masker).shap_values(xt)), None
    if type(classifier).__name__ in {"HistGradientBoostingClassifier", "RandomForestClassifier"}:
        values = np.asarray(shap.TreeExplainer(classifier).shap_values(xt))
        return values, (2 if values.ndim == 3 else None)
    raise ValueError(f"No hay explicador SHAP para {type(classifier).__name__}.")


def contributions(model: Pipeline, x: pd.DataFrame, reference: pd.DataFrame, favorable_label) -> pd.DataFrame:
    """Contribución de cada variable de origen al resultado favorable (filas de `x`)."""
    preprocessing, classifier = model[:-1], model[-1]
    xt = np.asarray(preprocessing.transform(x), dtype=float)
    ref = reference.sample(min(BACKGROUND_SIZE, len(reference)), random_state=0)
    background = np.asarray(preprocessing.transform(ref), dtype=float)

    values, class_axis = _shap_values(classifier, xt, background)
    classes = list(classifier.classes_)
    if class_axis is not None:
        values = values[:, :, classes.index(favorable_label)]
    elif classes[1] != favorable_label:  # binario: SHAP explica la clase classes_[1]
        values = -values

    sources = _output_sources(preprocessing[-1])
    per_output = pd.DataFrame(values, index=x.index, columns=range(values.shape[1]))
    return per_output.T.groupby(np.array(sources)).sum().T[list(dict.fromkeys(sources))]


def rejection_reasons(
    model: Pipeline,
    x: pd.DataFrame,
    reference: pd.DataFrame,
    decisions: pd.Series,
    favorable_label,
    top_k: int = 3,
) -> pd.DataFrame:
    """Factores principales de cada rechazo: hasta `top_k` variables con contribución negativa,
    de la más negativa a la menos. `x` y `decisions` (1 = favorable) comparten el índice, que
    identifica al solicitante (en la operación, su seudónimo)."""
    rejected = x[decisions.reindex(x.index).to_numpy() == 0]
    cols = ["pseudo_id", "rank", "feature", "contribution"]
    if rejected.empty:
        return pd.DataFrame(columns=cols)
    contrib = contributions(model, rejected, reference, favorable_label)
    rows = []
    for pid, row in contrib.iterrows():
        negative = row[row < 0].sort_values()[:top_k]
        rows += [(pid, rank, feature, float(value)) for rank, (feature, value) in enumerate(negative.items(), 1)]
    return pd.DataFrame(rows, columns=cols)


def top_k_agreement(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    """Estabilidad de las razones entre dos modelos (Cap. 6, 6.4): para los solicitantes que ambos
    rechazan, la proporción con el mismo conjunto de factores principales y el solapamiento medio
    de esos conjuntos (índice de Jaccard)."""
    sets_a = a.groupby("pseudo_id")["feature"].agg(frozenset)
    sets_b = b.groupby("pseudo_id")["feature"].agg(frozenset)
    common = sets_a.index.intersection(sets_b.index)
    if common.empty:
        return {"applicants": 0, "identical": float("nan"), "overlap": float("nan")}
    pairs = [(sets_a[i], sets_b[i]) for i in common]
    overlap = [len(p & q) / max(len(p | q), 1) for p, q in pairs]
    out = {
        "applicants": len(common),
        "identical": float(np.mean([p == q for p, q in pairs])),
        "overlap": float(np.mean(overlap)),
    }
    if "rank" in a.columns and "rank" in b.columns:  # coincidencia del factor principal (rango 1)
        first_a = a[a["rank"] == 1].set_index("pseudo_id")["feature"]
        first_b = b[b["rank"] == 1].set_index("pseudo_id")["feature"]
        both = first_a.index.intersection(first_b.index)
        out["first_identical"] = float((first_a[both] == first_b[both]).mean()) if len(both) else float("nan")
    return out


__all__ = ["contributions", "rejection_reasons", "top_k_agreement"]
