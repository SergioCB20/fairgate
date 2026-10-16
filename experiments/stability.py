"""Estabilidad de las razones de rechazo (Cap. 6, 6.4): coincidencia de los tres factores principales
de una misma solicitud entre modelos entrenados con distintas semillas.

Para que "la misma solicitud" esté definida, todos los modelos explican el mismo conjunto: el de
prueba de la partición de desarrollo (semilla de `dataset.yaml`). Cada semilla entrena el modelo con
una submuestra distinta (sin reemplazo, `fraction`) de la partición de entrenamiento, y se compara
cada modelo con el de referencia (entrenado con toda la partición) y todos los pares entre sí.
"""
from __future__ import annotations

import itertools
import statistics

import numpy as np
import pandas as pd

from fairgate.data import load_batch, load_domain, split
from fairgate.explanations import rejection_reasons, top_k_agreement
from fairgate.preprocessing import build_model_pipeline

from .protocol import Protocol
from .scenarios import with_seed


def _reasons(domain, model, train: pd.DataFrame, test: pd.DataFrame, top_k: int) -> pd.DataFrame:
    ds = domain.dataset
    x = test[ds.features.all]
    decisions = pd.Series((model.predict(x) == ds.favorable_label).astype(int), index=x.index)
    return rejection_reasons(model, x, train[ds.features.all], decisions, ds.favorable_label, top_k)


def reason_stability(proto: Protocol, seeds: list[int], estimator: str | None = None, fraction: float = 0.8) -> dict:
    base = load_domain(proto.domain)
    if estimator:
        base = with_seed(base, base.dataset.split.random_state, estimator)
    ds = base.dataset
    top_k = int(base.contracts["QA_GATE_4"].params.get("reason_top_k", 3))
    df, _ = load_batch(base)
    train, test = split(base, df)

    def fit(data: pd.DataFrame, seed: int):
        return build_model_pipeline(ds.features, ds.model, random_state=seed).fit(data[ds.features.all], data[ds.target])

    reference = _reasons(base, fit(train, ds.split.random_state), train, test, top_k)
    per_seed = {}
    for s in seeds:
        sub = train.sample(frac=fraction, random_state=s)
        per_seed[s] = _reasons(base, fit(sub, s), sub, test, top_k)

    vs_ref = [top_k_agreement(reference, r) for r in per_seed.values()]
    pairs = [top_k_agreement(per_seed[a], per_seed[b]) for a, b in itertools.combinations(seeds, 2)]

    def summary(xs):
        ident = [x["identical"] for x in xs if not np.isnan(x["identical"])]
        over = [x["overlap"] for x in xs if not np.isnan(x["overlap"])]
        first = [x["first_identical"] for x in xs if not np.isnan(x.get("first_identical", np.nan))]
        return {"comparisons": len(xs),
                "identical_median": statistics.median(ident) if ident else None,
                "identical_min": min(ident) if ident else None,
                "first_identical_median": statistics.median(first) if first else None,
                "first_identical_min": min(first) if first else None,
                "overlap_median": statistics.median(over) if over else None,
                "applicants_median": statistics.median(x["applicants"] for x in xs) if xs else 0}

    first = reference[reference["rank"] == 1]["feature"].value_counts().to_dict()
    return {"estimator": ds.model.estimator, "seeds": seeds, "fraction": fraction, "top_k": top_k,
            "rejected_reference": int(reference["pseudo_id"].nunique()),
            "vs_reference": summary(vs_ref), "pairwise": summary(pairs), "rank1_reference": first}
