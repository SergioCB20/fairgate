"""Preprocesamiento en pasos explícitos (imputación → escalado → codificación).

El mismo diseño se usa de dos formas:
- `stepwise_outputs`: devuelve la salida de cada paso, para que el Contrato C2 mida la
  filtración del atributo protegido después de cada transformador (ADR-006).
- `build_model_pipeline`: el pipeline de scikit-learn equivalente, para entrenar el modelo.
"""
from __future__ import annotations

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .schema import FeatureSpec, ModelSpec

STEPS = ("entrada", "imputacion", "escalado", "codificacion")

# Catálogo de clasificadores base: (clase, parámetros por defecto). Todos aceptan sample_weight.
ESTIMATORS = {
    "logistic_regression": (LogisticRegression, {"class_weight": "balanced", "max_iter": 2000}),
    "random_forest": (RandomForestClassifier, {"class_weight": "balanced", "n_estimators": 200}),
    "hist_gradient_boosting": (HistGradientBoostingClassifier, {"class_weight": "balanced"}),
}


def build_estimator(spec: ModelSpec, random_state: int = 42):
    cls, defaults = ESTIMATORS[spec.estimator]
    return cls(**{**defaults, "random_state": random_state, **spec.params})


def stepwise_outputs(train: pd.DataFrame, features: FeatureSpec) -> list[tuple[str, pd.DataFrame]]:
    """Salida de cada paso de preprocesamiento sobre el conjunto de entrenamiento."""
    num, cat = list(features.numeric), list(features.categorical)
    x = train[num + cat].copy()
    outputs = [("entrada", x.copy())]

    if num:
        x[num] = SimpleImputer(strategy="median").fit_transform(x[num])
    if cat:
        x[cat] = SimpleImputer(strategy="most_frequent").fit_transform(x[cat])
    outputs.append(("imputacion", x.copy()))

    if num:
        x[num] = StandardScaler().fit_transform(x[num])
    outputs.append(("escalado", x.copy()))

    if cat:
        enc = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
        encoded = pd.DataFrame(
            enc.fit_transform(x[cat]), columns=enc.get_feature_names_out(cat), index=x.index
        )
        x = pd.concat([x[num], encoded], axis=1)
    outputs.append(("codificacion", x.copy()))
    return outputs


def build_model_pipeline(
    features: FeatureSpec, model: ModelSpec | None = None, random_state: int = 42
) -> Pipeline:
    """Clasificador base declarado en `dataset.yaml` (por defecto, regresión logística con pesos
    de clase balanceados; Cap. 4, Zona 2)."""
    transformers = []
    if features.numeric:
        transformers.append(
            ("num", Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]),
             list(features.numeric))
        )
    if features.categorical:
        transformers.append(
            ("cat", Pipeline([
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
            ]), list(features.categorical))
        )
    return Pipeline([
        ("preprocessing", ColumnTransformer(transformers)),
        ("classifier", build_estimator(model or ModelSpec(), random_state)),
    ])
