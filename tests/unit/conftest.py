"""Datos y dominios sintéticos: las pruebas unitarias no necesitan el dataset real."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml


@pytest.fixture(autouse=True)
def _no_lineage(monkeypatch):
    monkeypatch.setenv("FAIRGATE_LINEAGE", "0")


def synthetic_frame(n=2000, minority=0.5, proxy_strength=0.0, bias=0.0, seed=0) -> pd.DataFrame:
    """z: grupo protegido; p: variable que imita a z con fuerza `proxy_strength`;
    y depende de x1 y, con fuerza `bias`, de z."""
    rng = np.random.default_rng(seed)
    z = np.where(rng.random(n) < minority, 1, 2)
    x1 = rng.normal(size=n)
    c1 = rng.integers(0, 4, size=n)
    p = np.where(rng.random(n) < proxy_strength, z, rng.integers(1, 3, size=n))
    logit = 1.5 * x1 + bias * (z == 2) - 0.2
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    age = rng.integers(18, 70, size=n)
    return pd.DataFrame({"y": y, "z": z, "x1": x1, "c1": c1, "p": p, "age": age})


def write_domain(tmp_path, df, numeric=("x1",), categorical=("c1",), c1_rules=None, c3_remediation=True):
    data = tmp_path / "data.csv"
    df.to_csv(data, index=False)
    attrs = [
        {"name": "z", "groups": [1, 2], "unprivileged": None, "source_columns": ["z"]},
    ]
    dataset = {
        "name": "sint",
        "path": str(data),
        "target": "y",
        "columns": [
            {"name": "y", "dtype": "int", "allowed_values": [0, 1]},
            {"name": "z", "dtype": "int", "allowed_values": [1, 2]},
            {"name": "x1", "dtype": "float"},
        ],
        "features": {"numeric": list(numeric), "categorical": list(categorical)},
    }
    c1 = {
        "contract_id": "C1", "version": "1", "gate": "QA_GATE_1", "stage": "datos", "dataset": "sint",
        "protected_attributes": attrs,
        "rules": c1_rules or [
            {"id": "C1-FORBIDDEN", "metric": "forbidden_features", "operator": "le", "threshold": 0},
            {"id": "C1-REP", "metric": "min_group_proportion", "operator": "ge", "threshold": 0.05},
        ],
    }
    c2 = {
        "contract_id": "C2", "version": "1", "gate": "QA_GATE_2", "stage": "pasos", "dataset": "sint",
        "protected_attributes": attrs,
        "rules": [
            {"id": "C2-AUC", "metric": "leakage_auc", "operator": "le", "threshold": 0.60},
            {"id": "C2-INC", "metric": "leakage_auc_increment", "operator": "le", "threshold": 0.02},
        ],
        "params": {"folds": 3},
    }
    c3 = {
        "contract_id": "C3", "version": "1", "gate": "QA_GATE_3", "stage": "modelo", "dataset": "sint",
        "protected_attributes": attrs,
        "rules": [
            {"id": "C3-SPD", "metric": "spd", "operator": "le", "threshold": 0.10},
            {"id": "C3-ACC", "metric": "balanced_accuracy_drop", "operator": "le", "threshold": 0.05,
             "severity": "warn"},
        ],
        "statistics": {"method": "bootstrap", "n_resamples": 100},
    }
    if c3_remediation:
        c3["remediation"] = {"method": "reweighing"}
    c4 = {
        "contract_id": "C4", "version": "1", "gate": "QA_GATE_4", "stage": "lotes", "dataset": "sint",
        "protected_attributes": attrs,
        "rules": [
            {"id": "C4-DRIFT", "metric": "drift_share", "operator": "le", "threshold": 0.30, "severity": "warn"},
            {"id": "C4-SPD", "metric": "spd", "operator": "le", "threshold": 0.10},
            {"id": "C4-EOD", "metric": "eod", "operator": "le", "threshold": 0.10},
        ],
        "statistics": {"method": "bootstrap", "n_resamples": 100, "decide_on": "best_bound"},
    }
    dom = tmp_path / "dom"
    dom.mkdir()
    for name, content in (("dataset", dataset), ("c1", c1), ("c2", c2), ("c3", c3), ("c4", c4)):
        (dom / f"{name}.yaml").write_text(yaml.safe_dump(content, allow_unicode=True), encoding="utf-8")
    return dom
