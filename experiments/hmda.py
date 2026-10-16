"""Caso HMDA (escenario E6, Cap. 6): descarga y preparación de los datos.

Fuente: datos públicos de la Home Mortgage Disclosure Act (FFIEC/CFPB), API del Data Browser,
filtrados por estado y año, solo con solicitudes aprobadas (`action_taken` = 1) o denegadas (3).
Un año es la referencia (desarrollo: C1 a C3) y el siguiente, la producción (C4), partida en lotes.

La preparación es propia del caso, no del motor: convierte el formato del regulador (códigos,
rangos, "Exempt") en una tabla con el esquema de `domains/hmda/dataset.yaml`. El motor (`fairgate/`)
se configura solo con los YAML del dominio.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from fairgate.data import PROJECT_ROOT

URL = "https://ffiec.cfpb.gov/v2/data-browser-api/view/csv?states={state}&years={year}&actions_taken=1,3"
DATA = PROJECT_ROOT / "data" / "hmda"

# "No disponible" es una categoría que publica el regulador (el solicitante no la informó o no
# aplica), no un dato perdido: se codifica como categoría para que no cuente como nulo en el C1.
NA = "No disponible"
RACE = {
    "White": "White",
    "Black or African American": "Black",
    "Asian": "Asian",
    "American Indian or Alaska Native": "Other",
    "Native Hawaiian or Other Pacific Islander": "Other",
    "2 or more minority races": "Other",
    "Free Form Text Only": "Other",
    "Joint": "Joint",
    "Race Not Available": NA,
}
SEX = {"Male": "Male", "Female": "Female", "Joint": "Joint", "Sex Not Available": NA}
# Columnas que solo existen (o solo toman ciertos valores) cuando el crédito se otorgó: se generan
# después de la decisión y filtran la etiqueta. Se conservan en el CSV para que el C1 lo verifique.
POST_DECISION = {
    "interest_rate": "interest_rate",
    "rate_spread": "rate_spread",
    "total_loan_costs": "total_loan_costs",
    "purchaser_type": "purchaser_type",
    "hoepa_status": "hoepa_status",
    "denial_reason-1": "denial_reason_1",
}


def download(state: str, year: int, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        with urllib.request.urlopen(URL.format(state=state, year=year), timeout=900) as r, open(dest, "wb") as f:
            f.write(r.read())
    return dest


def _dti(v) -> str:
    """El regulador publica la razón deuda/ingreso en rangos, salvo entre 36 % y 49 %, que la
    publica exacta; se agrupa en un solo rango para que la variable tenga una sola escala."""
    if pd.isna(v) or v == "Exempt":
        return NA
    if isinstance(v, str) and not v.replace(".", "").isdigit():
        return v
    return "36%-<50%"


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    """Tabla con el esquema de `dataset.yaml`. Se descartan los registros de entidades exentas de
    reportar los campos ampliados ("Exempt"), porque no tienen las variables del modelo."""
    exempt = raw["loan_to_value_ratio"].astype(str).eq("Exempt") | raw["loan_term"].astype(str).eq("Exempt")
    df = raw[~exempt]
    num = lambda c: pd.to_numeric(df[c], errors="coerce")  # noqa: E731
    out = pd.DataFrame({
        "label": (df["action_taken"] == 1).astype(int),
        "Sex": df["derived_sex"].map(SEX),
        "Race": df["derived_race"].map(RACE),
        "Age": df["applicant_age"].astype(str).replace({"8888": NA}),
        "loan_amount": num("loan_amount") / 1000,  # miles de dólares, como el ingreso
        "income": num("income"),
        "loan_to_value_ratio": num("loan_to_value_ratio"),
        "property_value": num("property_value") / 1000,
        "loan_term": num("loan_term"),
        "tract_minority_population_percent": num("tract_minority_population_percent"),
        "debt_to_income_ratio": df["debt_to_income_ratio"].map(_dti),
        "loan_type": df["loan_type"].astype(int),
        "loan_purpose": df["loan_purpose"].astype(int),
        "lien_status": df["lien_status"].astype(int),
        "occupancy_type": df["occupancy_type"].astype(int),
        "open_end_line_of_credit": df["open-end_line_of_credit"].astype(int),
        "business_or_commercial_purpose": df["business_or_commercial_purpose"].astype(int),
        "conforming_loan_limit": df["conforming_loan_limit"].fillna(NA).astype(str),
        "county_code": df["county_code"].fillna(0).astype(int),
    })
    for src, dst in POST_DECISION.items():
        out[dst] = num(src) if src != "denial_reason-1" else df[src].astype(int)
    return out.reset_index(drop=True)


def prepare(state: str = "DE", reference_year: int = 2022, production_year: int = 2023,
            lots: int = 4, seed: int = 42) -> dict:
    """Descarga los dos años, escribe la referencia (`hmda-<estado>-<año>.csv`) y la producción en
    `lotes` lotes aleatorios y disjuntos (los datos públicos no traen la fecha de la decisión)."""
    raw = {y: pd.read_csv(download(state, y, DATA / "crudo" / f"{state.lower()}-{y}.csv"), low_memory=False)
           for y in (reference_year, production_year)}
    ref = clean(raw[reference_year])
    ref_path = DATA / f"hmda-{state.lower()}-{reference_year}.csv"
    ref.to_csv(ref_path, index=False)
    prod = clean(raw[production_year])
    folder = DATA / f"produccion-{production_year}"
    folder.mkdir(parents=True, exist_ok=True)
    order = np.random.default_rng(seed).permutation(len(prod))
    paths = []
    for i, idx in enumerate(np.array_split(order, lots), 1):
        p = folder / f"lote-{i:02d}.csv"
        prod.iloc[idx].to_csv(p, index=False)
        paths.append(p)
    return {"reference": ref_path, "reference_rows": len(ref), "excluded_exempt": len(raw[reference_year]) - len(ref),
            "production": paths, "production_rows": len(prod)}


def production_lots(production_year: int = 2023) -> list[Path]:
    return sorted((DATA / f"produccion-{production_year}").glob("lote-*.csv"))
