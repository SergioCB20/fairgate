"""Inyectores de los escenarios E0–E5 (Cap. 6, Tabla 20). Cada inyección usa la semilla de la
repetición, de modo que es reproducible, y devuelve lo que inyectó realmente (`info`).

Decisiones de implementación que el texto del protocolo no fija (ver
`estado/o4-implementacion.md` en la base de conocimiento):
- E1: el submuestreo se aplica al lote que ingresa (el que evalúa el C1), antes de la partición.
- E2: la variable sustituta coincide con el grupo en exactamente la fracción indicada de los
  registros; en el resto toma el valor de otro grupo.
- E3: los valores faltantes se inyectan en el lote que ingresa; el transformador sesgado imputa
  el percentil 90 a un grupo y el percentil 10 al otro, y el modelo se entrena con esa imputación.
- E4: las etiquetas se invierten solo en la partición de entrenamiento; el lote del C1 es la
  unión de entrenamiento (con la inversión) y prueba. E4R agrega antes una sustituta de la edad
  (variable del modelo), que es la ruta por la que el sesgo de las etiquetas llega a las decisiones.
- E5: en cada lote, una parte de los solicitantes aprobados del grupo recibe las variables de
  solicitantes rechazados del entrenamiento, hasta que la tasa de aprobación del grupo quede
  `disparidad` por debajo de la del resto.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from fairgate.data import Domain, assign_groups, split
from fairgate.monitoring import ProductionBatch
from fairgate.preprocessing import stepwise_outputs
from fairgate.schema import ColumnSpec

from .protocol import Protocol


@dataclass
class Prepared:
    """Datos de una repetición después de la inyección."""

    domain: Domain
    batch: pd.DataFrame  # lote que ingresa: lo evalúa el C1
    train: pd.DataFrame
    test: pd.DataFrame
    batch_hash: str
    c2_steps: list[tuple[str, pd.DataFrame]] | None = None
    info: dict = field(default_factory=dict)


def frame_hash(df: pd.DataFrame) -> str:
    return hashlib.md5(df.to_csv(index=False).encode("utf-8")).hexdigest()


def with_seed(domain: Domain, seed: int, estimator: str | None = None) -> Domain:
    """Copia del dominio con la partición de la repetición y, si se indica, otro clasificador."""
    ds = domain.dataset
    update = {"split": ds.split.model_copy(update={"random_state": seed})}
    if estimator:
        update["model"] = ds.model.model_copy(update={"estimator": estimator})
    return replace(domain, dataset=ds.model_copy(update=update))


def _attribute(domain: Domain, name: str):
    for contract in domain.contracts.values():
        for attr in contract.protected_attributes:
            if attr.name == name:
                return attr
    raise KeyError(f"Ningún contrato declara el atributo protegido '{name}'.")


def group_mask(domain: Domain, df: pd.DataFrame, attr_name: str, group: str) -> pd.Series:
    return assign_groups(df, _attribute(domain, attr_name)) == str(group)


# --------------------------------------------------------------------------- E1 a E4


def underrepresent(df: pd.DataFrame, mask: pd.Series, proportion: float, rng: np.random.Generator):
    """E1: submuestrea el grupo hasta que sea `proportion` del lote."""
    others = df[~mask]
    n_keep = min(int(round(proportion * len(others) / (1 - proportion))), int(mask.sum()))
    keep = df[mask].sample(n=n_keep, random_state=int(rng.integers(2**31)))
    out = pd.concat([others, keep]).sort_index()
    return out, {"group_rows": n_keep, "proportion": n_keep / len(out)}


def proxy_column(values: pd.Series, groups: list, coincidence: float, rng: np.random.Generator) -> pd.Series:
    """E2: coincide con `values` en una fracción `coincidence` de los registros; en el resto,
    toma el valor de otro grupo, elegido al azar."""
    match = rng.random(len(values)) < coincidence
    others = {g: [h for h in groups if h != g] for g in groups}
    swapped = [others[v][int(rng.integers(len(others[v])))] for v in values]
    return pd.Series(np.where(match, values.to_numpy(), swapped), index=values.index).astype(int)


def inject_missing(df: pd.DataFrame, column: str, rate: float, rng: np.random.Generator) -> pd.DataFrame:
    """E3: valores faltantes en una fracción `rate` de los registros."""
    out = df.copy()
    idx = rng.choice(out.index.to_numpy(), size=int(round(rate * len(out))), replace=False)
    out[column] = out[column].astype(float)
    out.loc[idx, column] = np.nan
    return out


def biased_impute(df: pd.DataFrame, column: str, groups: pd.Series, fill: dict) -> pd.DataFrame:
    """E3: transformador sesgado: imputa un valor distinto según el grupo protegido."""
    out = df.copy()
    missing = out[column].isna()
    out.loc[missing, column] = groups[missing].map(fill).astype(float)
    return out


def flip_labels(train: pd.DataFrame, mask: pd.Series, target: str, favorable, rate: float,
                rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    """E4: marca como incumplimiento una fracción `rate` de los buenos pagadores del grupo."""
    out = train.copy()
    unfavorable = next(v for v in sorted(out[target].unique()) if v != favorable)
    candidates = out.index[mask.reindex(out.index).to_numpy() & (out[target] == favorable).to_numpy()]
    flipped = rng.choice(candidates.to_numpy(), size=int(round(rate * len(candidates))), replace=False)
    out.loc[flipped, target] = unfavorable
    return out, {"flipped": len(flipped), "candidates": len(candidates)}


def _add_proxy(df: pd.DataFrame, domain: Domain, mask: pd.Series, column: str, coincidence: float,
               rng: np.random.Generator) -> tuple[pd.DataFrame, Domain]:
    """Variable binaria que coincide con la pertenencia al grupo en una fracción `coincidence` de los
    registros, agregada a la especificación como variable categórica del modelo."""
    df = df.copy()
    df[column] = proxy_column(mask.astype(int), [0, 1], coincidence, rng)
    ds = domain.dataset
    spec = ds.model_copy(update={
        "columns": [*ds.columns, ColumnSpec(name=column, dtype="int", allowed_values=[0, 1])],
        "features": ds.features.model_copy(update={"categorical": [*ds.features.categorical, column]}),
    })
    return df, replace(domain, dataset=spec)


def prepare(proto: Protocol, domain: Domain, df: pd.DataFrame, scenario: str, intensity, seed: int) -> Prepared:
    """Aplica la inyección de un escenario de desarrollo (E0 a E4) y particiona el lote."""
    rng = np.random.default_rng(seed)
    ds = domain.dataset
    info: dict = {}

    if scenario == "E1":
        df, info = underrepresent(df, group_mask(domain, df, proto.age_attr, proto.age_group), intensity, rng)
    elif scenario == "E2":
        attr = _attribute(domain, proto.sex_attr)
        groups = list(attr.groups)
        df = df.copy()
        df[proto.proxy_column] = proxy_column(df[attr.value_column], groups, intensity, rng)
        info = {"coincidence": float((df[proto.proxy_column] == df[attr.value_column]).mean())}
        spec = ds.model_copy(update={
            "columns": [*ds.columns, ColumnSpec(name=proto.proxy_column, dtype="int", allowed_values=groups)],
            "features": ds.features.model_copy(update={"categorical": [*ds.features.categorical, proto.proxy_column]}),
        })
        domain = replace(domain, dataset=spec)
    elif scenario == "E3":
        df = inject_missing(df, proto.e3_column, intensity, rng)
        observed = df[proto.e3_column].dropna()
        attr = _attribute(domain, proto.sex_attr)
        labels = [str(g) for g in attr.groups]
        fill = {labels[0]: float(observed.quantile(0.9)), **{g: float(observed.quantile(0.1)) for g in labels[1:]}}
        batch_hash = frame_hash(df)
        train_nan, test_nan = split(domain, df)
        train = biased_impute(train_nan, proto.e3_column, assign_groups(train_nan, attr), fill)
        test = biased_impute(test_nan, proto.e3_column, assign_groups(test_nan, attr), fill)
        steps = [("entrada", train_nan[ds.features.all].copy()), *stepwise_outputs(train, ds.features)[1:]]
        info = {"missing": int(df[proto.e3_column].isna().sum()), "fill": fill}
        return Prepared(domain, df, train, test, batch_hash, steps, info)
    elif scenario in ("E4", "E4R"):
        if scenario == "E4R":  # sustituta débil de la edad, agregada como variable del modelo
            df, domain = _add_proxy(df, domain, group_mask(domain, df, proto.age_attr, proto.age_group),
                                    proto.age_proxy_column, proto.e4r_coincidence, rng)
            ds = domain.dataset
        train, test = split(domain, df)
        mask = group_mask(domain, train, proto.age_attr, proto.age_group)
        train, info = flip_labels(train, mask, ds.target, ds.favorable_label, intensity, rng)
        batch = pd.concat([train, test]).sort_index()
        return Prepared(domain, batch, train, test, frame_hash(batch), None, info)
    elif scenario != "E0":
        raise ValueError(f"{scenario} no es un escenario de desarrollo (E0 a E4).")

    train, test = split(domain, df)
    return Prepared(domain, df, train, test, frame_hash(df), None, info)


# --------------------------------------------------------------------------- E5


def production_batches(test: pd.DataFrame, lot_size: int, seed: int) -> list[pd.DataFrame]:
    """Particiones disjuntas del conjunto de prueba de unos `lot_size` registros."""
    n = max(1, int(round(len(test) / lot_size)))
    order = np.random.default_rng(seed).permutation(len(test))
    return [test.iloc[idx].reset_index(drop=True) for idx in np.array_split(order, n)]


def induce_disparity(batch: pd.DataFrame, mask: pd.Series, model, features: list[str], pool: pd.DataFrame,
                     favorable, disparity: float, rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    """E5: desplaza las variables de solicitantes aprobados del grupo hacia las de solicitantes
    rechazados (`pool`), hasta que su tasa de aprobación quede `disparity` bajo la del resto."""
    out = batch.copy()
    approved = model.predict(out[features]) == favorable
    m = mask.to_numpy()
    rate_g, rate_rest = approved[m].mean(), approved[~m].mean()
    info = {"base_spd": float(rate_rest - rate_g), "shifted": 0}
    if disparity <= 0 or m.sum() == 0:
        return out, info
    k = int(round((rate_g - max(rate_rest - disparity, 0.0)) * m.sum()))
    candidates = out.index[m & approved].to_numpy()
    k = min(max(k, 0), len(candidates))
    if k:
        idx = rng.choice(candidates, size=k, replace=False)
        donors = pool.sample(n=k, replace=len(pool) < k, random_state=int(rng.integers(2**31)))
        for c in features:
            out.loc[idx, c] = donors[c].to_numpy()
    info["shifted"] = k
    return out, info


def e5_batches(proto: Protocol, domain: Domain, model, train: pd.DataFrame, test: pd.DataFrame,
               disparity: float, lot_size: int, seed: int) -> tuple[list[ProductionBatch], list[dict]]:
    """Lotes de producción del E5 para una disparidad y un tamaño de lote."""
    ds = domain.dataset
    features = ds.features.all
    pool = train[model.predict(train[features]) != ds.favorable_label]
    rng = np.random.default_rng(seed)
    batches, infos = [], []
    for i, b in enumerate(production_batches(test, lot_size, seed), 1):
        mask = group_mask(domain, b, proto.age_attr, proto.age_group)
        injected, info = induce_disparity(b, mask, model, features, pool, ds.favorable_label, disparity, rng)
        batches.append(ProductionBatch(f"lote-{i:02d}", injected))
        infos.append(info)
    return batches, infos
