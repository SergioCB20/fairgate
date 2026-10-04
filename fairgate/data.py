"""Carga del dominio (especificación + contratos) y del lote de datos."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.model_selection import train_test_split

from .schema import Contract, DatasetSpec, ProtectedAttribute, load_contract, load_dataset_spec

PROJECT_ROOT = Path(__file__).resolve().parents[1]

GATE_ORDER = ["QA_GATE_1", "QA_GATE_2", "QA_GATE_3", "QA_GATE_4"]


@dataclass
class Domain:
    """Un caso de estudio: su dataset y sus contratos (domains/<nombre>/)."""

    path: Path
    dataset: DatasetSpec
    contracts: dict[str, Contract] = field(default_factory=dict)

    @property
    def data_path(self) -> Path:
        p = Path(self.dataset.path)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def data_available(self) -> bool:
        return self.data_path.exists()

    def contracts_in_order(self) -> list[Contract]:
        return [self.contracts[g] for g in GATE_ORDER if g in self.contracts]


def load_domain(path: str | Path) -> Domain:
    path = Path(path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    dataset = load_dataset_spec(path / "dataset.yaml")
    contracts: dict[str, Contract] = {}
    for f in sorted(path.glob("c*.yaml")):
        c = load_contract(f)
        if c.dataset != dataset.name:
            raise ValueError(f"{f.name}: el contrato es del dataset '{c.dataset}', no de '{dataset.name}'.")
        if c.gate in contracts:
            raise ValueError(f"{f.name}: hay dos contratos para {c.gate}.")
        contracts[c.gate] = c
    return Domain(path=path, dataset=dataset, contracts=contracts)


def file_hash(path: Path) -> str:
    """Hash MD5 del archivo; si existe su descriptor DVC, se usa el hash registrado por DVC."""
    dvc_file = path.with_name(path.name + ".dvc")
    if dvc_file.exists():
        with open(dvc_file, encoding="utf-8") as f:
            outs = (yaml.safe_load(f) or {}).get("outs", [])
        if outs and outs[0].get("md5"):
            return outs[0]["md5"]
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_batch(domain: Domain) -> tuple[pd.DataFrame, str]:
    """Lee el lote crudo y descarta las columnas que filtran la etiqueta."""
    df = pd.read_csv(domain.data_path)
    leak = [c for c in domain.dataset.leakage_columns if c in df.columns]
    return df.drop(columns=leak), file_hash(domain.data_path)


def assign_groups(df: pd.DataFrame, attr: ProtectedAttribute) -> pd.Series:
    """Etiqueta de grupo (str) de cada fila para un atributo protegido; NaN si no pertenece a ninguno."""
    labels = pd.Series(np.nan, index=df.index, dtype=object)
    if isinstance(attr.groups, dict):
        for label, rule in attr.groups.items():
            if isinstance(rule, str):
                mask = df.eval(rule).astype(bool)
            else:
                mask = df[attr.value_column].isin(rule)
            labels[mask & labels.isna()] = str(label)
    else:
        col = df[attr.value_column]
        for value in attr.groups:
            labels[(col == value) & labels.isna()] = str(value)
    return labels


def group_frame(df: pd.DataFrame, attrs: list[ProtectedAttribute]) -> pd.DataFrame:
    return pd.DataFrame({a.name: assign_groups(df, a) for a in attrs}, index=df.index)


def split(domain: Domain, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    s = domain.dataset.split
    return train_test_split(
        df, test_size=s.test_size, random_state=s.random_state, stratify=df[domain.dataset.target]
    )
