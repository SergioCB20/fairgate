"""Protocolo experimental del Objetivo 4 (Cap. 6): escenarios, intensidades, semillas y verdad
de referencia (Tabla 20). Todo lo que el Cap. 6 fija antes de ejecutar está aquí.

Los nombres de atributos y variables son parámetros, para poder probar la infraestructura con
dominios sintéticos; `DAVRONOV` es la instancia del caso de estudio.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Semillas (6.2.4 y 6.2.5). La de desarrollo (42) es la de `dataset.yaml` y de la calibración del
# C4 con 20 particiones (ADR-017). Las de calibración se reservan para fijar el umbral de deriva del
# C4; las de evaluación solo se usan con los contratos congelados. Las de humo verifican la
# infraestructura y no producen resultados de la tesis.
SEEDS: dict[str, list[int]] = {
    "desarrollo": [42],
    "calibracion": list(range(1000, 1030)),
    "evaluacion": list(range(2000, 2030)),
    "humo": list(range(9000, 9003)),
}

# E4R (E4 con ruta) se agregó tras la corrida de humo y la calibración (estado/o4-implementacion.md).
SCENARIOS = ("E0", "E1", "E2", "E3", "E4", "E4R", "E5")
CONFIGS = ("B0", "B2", "P-C1", "P-C2", "P")
# Compuertas activas en cada configuración (Tabla 21). En B0 el C3 no remedia.
CONFIG_GATES: dict[str, tuple[str, ...]] = {
    "B0": ("C3",),
    "B2": ("C3", "C4"),
    "P-C1": ("C2", "C3", "C4"),
    "P-C2": ("C1", "C3", "C4"),
    "P": ("C1", "C2", "C3", "C4"),
}
GATE_ORDER = ("C1", "C2", "C3", "C4")
GATE_STAGE = {"C1": "datos", "C2": "transformacion", "C3": "modelo", "C4": "operacion"}


@dataclass(frozen=True)
class Expected:
    """Verdad de referencia de una combinación de escenario e intensidad."""

    gate: str | None  # None: no debería bloquear ninguna compuerta
    rules: tuple[str, ...] = ()  # alguna de estas reglas debe estar entre las que fallan
    step: str | None = None  # C2: paso en que debe señalarse la filtración


@dataclass(frozen=True)
class Protocol:
    domain: str
    age_attr: str  # E1, E4 y E5
    age_group: str
    sex_attr: str  # E2 y E3
    e3_column: str  # variable numérica con valores faltantes inyectados (E3)
    proxy_column: str = "Proxy_sint"  # variable sustituta sintética (E2)
    e1_proportions: tuple[float, ...] = (0.06, 0.04, 0.03, 0.01)
    e2_coincidence: tuple[float, ...] = (0.60, 0.75, 0.90)
    e3_missing: tuple[float, ...] = (0.10, 0.20, 0.30)
    e4_flip: tuple[float, ...] = (0.05, 0.10, 0.20, 0.30)
    # E4R: E4 con una ruta hacia el modelo, una sustituta de la edad. Con 58 % de coincidencia el sesgo
    # no llegaba a las decisiones; con 75 %, sí (y el C2 la detecta).
    e4r_coincidence: float = 0.75
    age_proxy_column: str = "Proxy_edad"
    # Disparidad 0: el E0 por tamaño de lote (falsos positivos del C4 según el lote, 6.2.3).
    e5_disparity: tuple[float, ...] = (0.0, 0.05, 0.10, 0.20, 0.30)
    e5_lot_sizes: tuple[int, ...] = (218, 435, 871, 1742)
    default_batches: int = 4  # lotes del C4 en E0–E4 (los de `c4.yaml`)
    rep_threshold: float = 0.05  # C1-REP
    c4_spd_threshold: float = 0.10  # C4-SPD
    extra: dict = field(default_factory=dict)

    def intensities(self, scenario: str) -> tuple:
        return {
            "E0": (None,),
            "E1": self.e1_proportions,
            "E2": self.e2_coincidence,
            "E3": self.e3_missing,
            "E4": self.e4_flip,
            "E4R": self.e4_flip,
            "E5": tuple((d, n) for d in self.e5_disparity for n in self.e5_lot_sizes),
        }[scenario]

    def strongest(self, scenario: str):
        """Intensidad más severa de un escenario de inyección. En E1 es la proporción más baja
        (menos representación); en los demás, el valor más alto."""
        return (min if scenario == "E1" else max)(self.intensities(scenario))

    def expected(self, scenario: str, intensity) -> Expected:
        """Tabla 20. Las intensidades por debajo del umbral esperan que no se bloquee."""
        if scenario == "E0":
            return Expected(None)
        if scenario == "E1":
            return Expected("C1", ("C1-REP",)) if intensity < self.rep_threshold else Expected(None)
        if scenario == "E2":
            return Expected("C2", ("C2-AUC",), "entrada")
        if scenario == "E3":  # los faltantes inyectados violan primero el contrato de los datos
            return Expected("C1", ("C1-NULLS",))
        if scenario == "E4":
            return Expected("C3", ("C3-SPD", "C3-EOD", "C3-DI"))
        if scenario == "E4R":  # la sustituta es la ruta del sesgo: la detecta el C2 en la entrada
            return Expected("C2", ("C2-AUC",), "entrada")
        if scenario == "E5":
            disparity, _ = intensity
            return Expected("C4", ("C4-SPD",)) if disparity > self.c4_spd_threshold else Expected(None)
        raise ValueError(f"Escenario desconocido: {scenario}")

    def secondary(self, scenario: str) -> Expected | None:
        """Segunda localización que se reporta aparte, sin importar el orden de las compuertas:
        en E3, el transformador sesgado (C2-INC en la imputación); en E4R, el daño en el modelo (C3)."""
        return {
            "E3": Expected("C2", ("C2-INC",), "imputacion"),
            "E4R": Expected("C3", ("C3-SPD", "C3-EOD", "C3-DI")),
        }.get(scenario)

    def injected_column(self, scenario: str) -> str | None:
        """Variable que debe aparecer entre las que mejor separan los grupos en el C2."""
        return {"E2": self.proxy_column, "E4R": self.age_proxy_column}.get(scenario)


DAVRONOV = Protocol(
    domain="domains/davronov",
    age_attr="Age_group",
    age_group="<25",
    sex_attr="Sex",
    e3_column="INPS_mln_sum",
)
