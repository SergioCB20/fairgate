"""Zona 3: scoring por lotes y monitoreo continuo, con el Contrato C4 (Cap. 4, Figura 7; ADR-010).

Flujo por lote de producción B_t:
1. Captura y seudonimización: cada registro recibe un identificador seudonimizado (HMAC). El
   atributo protegido y la etiqueta observada se guardan en almacenes separados, asociados a
   ese identificador; el scorer no los recibe.
2. Scorer por lotes: el modelo aprobado puntúa solo las variables del modelo. El generador de
   razones de rechazo obtiene, con SHAP, los factores principales de cada rechazo
   (`explanations.py`; `params.reason_top_k` del C4, 3 por defecto, 0 para desactivarlo).
3. Monitor de deriva de datos: compara cada variable del lote con la de entrenamiento.
4. Monitor de deriva del sesgo: recalcula las reglas de equidad del C3 sobre el lote.
5. QA Gate 4: si una regla 'block' se incumple, se emite una alerta de deriva del sesgo y se
   dispara el reentrenamiento (Trigger CT). La deriva de datos solo se registra ('warn').

Las pruebas de deriva reproducen las que Evidently elige por defecto (ADR-016): con una
referencia de más de 1 000 registros, la distancia de Wasserstein normalizada (variables
numéricas con más de 5 valores) o la distancia de Jensen-Shannon (el resto), con umbral 0,1;
con una referencia menor, Kolmogorov-Smirnov o chi-cuadrado, con p < 0,05.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.spatial import distance

from . import lineage
from .data import Domain, group_frame, load_batch, load_domain, split
from .gates import check_contract, group_fairness_results
from .results import GateResult, RuleResult, evaluate, not_applicable
from .schema import Contract

PSEUDONYM_KEY_ENV = "FAIRGATE_PSEUDONYM_KEY"


class MonitorError(Exception):
    """No hay un modelo aprobado o el lote no se puede monitorear."""


# --------------------------------------------------------------------------- lotes de producción


@dataclass
class ProductionBatch:
    """Lote tal como llega a la operación: variables, atributos protegidos y, si ya se conoce,
    la etiqueta observada (en el crédito llega meses después; Cap. 4, 4.5.5)."""

    batch_id: str
    data: pd.DataFrame

    @property
    def hash(self) -> str:
        return hashlib.md5(self.data.to_csv(index=False).encode("utf-8")).hexdigest()


def simulate_batches(test: pd.DataFrame, n_batches: int, random_state: int = 42) -> list[ProductionBatch]:
    """Operación simulada (Cap. 4, 4.5.5): Davronov no tiene marcas temporales, así que los lotes
    son particiones aleatorias y disjuntas del conjunto de prueba. Sin inyección, es el escenario
    de control: no hay deriva por construcción."""
    if n_batches < 1:
        raise ValueError("n_batches debe ser al menos 1.")
    order = np.random.default_rng(random_state).permutation(len(test))
    return [
        ProductionBatch(f"lote-{i + 1:02d}", test.iloc[idx].reset_index(drop=True))
        for i, idx in enumerate(np.array_split(order, n_batches))
    ]


def read_batch(path: str | Path, domain: Domain) -> ProductionBatch:
    """Lee un lote de producción desde un CSV y descarta las columnas que filtran la etiqueta."""
    path = Path(path)
    df = pd.read_csv(path)
    leak = [c for c in domain.dataset.leakage_columns if c in df.columns]
    return ProductionBatch(path.stem, df.drop(columns=leak))


# --------------------------------------------------------------------------- captura y scoring


class Pseudonymizer:
    """Identificador seudonimizado de cada registro: HMAC-SHA256 con una clave secreta.

    La clave se lee de FAIRGATE_PSEUDONYM_KEY. Si no está definida, se genera una clave efímera:
    los seudónimos no se pueden volver a vincular con el registro una vez terminado el proceso.
    """

    def __init__(self, key: bytes | None = None):
        env = os.environ.get(PSEUDONYM_KEY_ENV)
        self.ephemeral = key is None and not env
        self.key = key or (env.encode("utf-8") if env else os.urandom(32))

    def __call__(self, batch_id: str, n: int) -> list[str]:
        return [
            hmac.new(self.key, f"{batch_id}:{i}".encode("utf-8"), hashlib.sha256).hexdigest()[:16]
            for i in range(n)
        ]


@dataclass
class ScoredBatch:
    batch: ProductionBatch
    decisions: pd.DataFrame  # por seudónimo: score y decisión (1 = resultado favorable)
    protected: pd.DataFrame  # almacén separado: grupo de cada atributo protegido, por seudónimo
    outcomes: pd.Series | None  # almacén separado: etiqueta observada (1 = favorable), si existe
    reasons: pd.DataFrame | None = None  # factores principales de cada rechazo, por seudónimo


def score_batch(
    domain: Domain, contract: Contract, model, batch: ProductionBatch, pseudonymizer: Pseudonymizer
) -> ScoredBatch:
    ds = domain.dataset
    df = batch.data.reset_index(drop=True)
    missing = [c for c in ds.features.all if c not in df.columns]
    if missing:
        raise MonitorError(f"{batch.batch_id}: faltan variables del modelo: {missing}")
    ids = pd.Index(pseudonymizer(batch.batch_id, len(df)), name="pseudo_id")

    # El scorer recibe solo las variables del modelo: nunca el atributo protegido (Cap. 4, Zona 3).
    x = df[ds.features.all]
    leaked = sorted(contract.forbidden_columns & set(x.columns))
    if leaked:
        raise MonitorError(f"Columnas prohibidas entre las variables del scorer: {leaked}")
    classes = list(model.classes_)
    fav = classes.index(ds.favorable_label)
    proba = model.predict_proba(x)[:, fav]
    decision = (model.predict(x) == ds.favorable_label).astype(int)
    decisions = pd.DataFrame({"score": proba, "decision": decision}, index=ids)

    protected = group_frame(df, contract.protected_attributes)
    protected.index = ids
    outcomes = None
    if ds.target in df.columns and df[ds.target].notna().all():
        outcomes = pd.Series((df[ds.target] == ds.favorable_label).astype(int).to_numpy(), index=ids)
    return ScoredBatch(batch, decisions, protected, outcomes)


# --------------------------------------------------------------------------- deriva de datos


def _counts(ref: pd.Series, cur: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Frecuencia absoluta de cada valor observado en la referencia o en el lote."""
    keys = sorted(set(ref.unique()) | set(cur.unique()), key=str)
    r = ref.value_counts().reindex(keys, fill_value=0).to_numpy(dtype=float)
    c = cur.value_counts().reindex(keys, fill_value=0).to_numpy(dtype=float)
    return r, c


def column_drift(ref: pd.Series, cur: pd.Series, numeric: bool, threshold: float = 0.1) -> dict:
    """Prueba de deriva de una variable con el criterio por defecto de Evidently 0.7
    (`_get_default_stattest`; ADR-016). `threshold` es el de las distancias."""
    ref, cur = ref.dropna(), cur.dropna()
    n_values = pd.concat([ref, cur]).nunique()
    continuous = numeric and n_values > 5
    if len(ref) > 1000:
        if continuous:
            test = "wasserstein"
            score = stats.wasserstein_distance(ref, cur) / max(float(np.std(ref)), 0.001)
        else:
            test = "jensenshannon"
            r, c = _counts(ref, cur)
            score = float(distance.jensenshannon(r / len(ref), c / len(cur)))
        drift = score >= threshold
    else:
        if continuous:
            test, score = "ks", float(stats.ks_2samp(ref, cur).pvalue)
        else:
            test = "chi2"  # Evidently usa una prueba Z de proporciones si hay solo 2 valores
            r, c = _counts(ref, cur)
            score = float(stats.chisquare(c, r * len(cur) / len(ref)).pvalue)
        drift = score < 0.05
    return {"test": test, "score": round(float(score), 4), "drift": bool(drift)}


def data_drift(reference: pd.DataFrame, current: pd.DataFrame, numeric: list[str], threshold: float) -> dict:
    cols = {c: column_drift(reference[c], current[c], c in numeric, threshold) for c in reference.columns}
    drifted = [c for c, r in cols.items() if r["drift"]]
    return {"share": len(drifted) / len(cols), "drifted": drifted, "columns": cols}


# --------------------------------------------------------------------------- C4


def run_c4(contract: Contract, domain: Domain, scored: ScoredBatch, reference: pd.DataFrame) -> GateResult:
    """QA Gate 4 sobre un lote puntuado. `reference` son las variables del entrenamiento."""
    ds = domain.dataset
    threshold = float(contract.params.get("stattest_threshold", 0.1))
    y_pred = scored.decisions["decision"].to_numpy()
    # SPD y DI solo usan la decisión; la EOD necesita la etiqueta observada.
    y_true = scored.outcomes.to_numpy() if scored.outcomes is not None else np.zeros_like(y_pred)

    results: list[RuleResult] = []
    for rule in contract.rules:
        if rule.metric == "drift_share":
            dd = data_drift(reference[ds.features.all], scored.batch.data[ds.features.all], ds.features.numeric,
                            threshold)
            results.append(evaluate(rule, dd["share"], details={"drifted": dd["drifted"], "columns": dd["columns"]}))
        elif rule.metric == "eod" and scored.outcomes is None:
            results += [not_applicable(rule, a.name, "etiquetas aún no observadas") for a in contract.protected_attributes]
        else:
            results += group_fairness_results(contract, rule, y_true, y_pred, scored.protected)

    res = GateResult.new(
        contract, scored.batch.hash, f"lote:{scored.batch.batch_id}", results,
        batch_id=scored.batch.batch_id,
        records_count=len(scored.batch.data),
        labels_observed=scored.outcomes is not None,
        favorable_rate=float(y_pred.mean()) if len(y_pred) else float("nan"),
    )
    failed = {r.metric for r in res.rules if r.applicable and not r.passed}
    res.extra["data_drift_alert"] = "drift_share" in failed
    res.extra["bias_drift_alert"] = not res.passed
    res.extra["trigger_ct"] = not res.passed  # reentrenamiento hacia la Zona 1 (ADR-010)
    return res


@dataclass
class BatchOutcome:
    scored: ScoredBatch
    result: GateResult
    run_id: str | None = None


@dataclass
class Monitor:
    """Operación del modelo aprobado: puntúa lotes, ejecuta el C4 y registra cada lote en MLflow.

    Se construye desde una sesión del pipeline (`from_session`) o desde el registro de modelos de
    MLflow (`from_registry`), que es el camino del despliegue (Trigger CD).
    """

    domain: Domain
    model: object
    reference: pd.DataFrame
    training_hash: str
    pipeline_run_id: str | None = None
    model_run_id: str | None = None
    log_lineage: bool = False
    pseudonymizer: Pseudonymizer = field(default_factory=Pseudonymizer)
    outcomes: list[BatchOutcome] = field(default_factory=list)

    def __post_init__(self):
        if "QA_GATE_4" not in self.domain.contracts:
            raise MonitorError(f"El dominio '{self.domain.dataset.name}' no declara un Contrato C4.")
        self.contract = self.domain.contracts["QA_GATE_4"]
        check_contract(self.contract, self.domain.dataset)
        self._lineage: lineage.Lineage | None = None

    # ------------------------------------------------------------------ construcción
    @classmethod
    def from_session(cls, session, log_lineage: bool | None = None) -> "Monitor":
        approved = session.approved_model()
        if approved is None:
            raise MonitorError("El C3 no aprobó ningún modelo: no hay nada que desplegar.")
        session.close()  # cierra la ejecución del pipeline antes de abrir la de la operación
        return cls(
            domain=session.domain,
            model=approved.model,
            reference=session.train,
            training_hash=session.batch_hash,
            pipeline_run_id=session.pipeline_run_id,
            model_run_id=session.run_ids.get(approved.subject),
            log_lineage=session.log_lineage if log_lineage is None else log_lineage,
        )

    @classmethod
    def from_registry(cls, domain: Domain | str | Path, tracking_uri: str | None = None) -> "Monitor":
        """Carga la última versión registrada de `<dataset>-scoring` y su lote de entrenamiento."""
        os.environ.setdefault("MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR", "false")
        import mlflow
        import mlflow.sklearn
        from mlflow import MlflowClient

        domain = domain if isinstance(domain, Domain) else load_domain(domain)
        mlflow.set_tracking_uri(tracking_uri or lineage.tracking_uri_default())
        client = MlflowClient()
        name = f"{domain.dataset.name}-scoring"
        versions = client.search_model_versions(f"name = '{name}'")
        if not versions:
            raise MonitorError(f"No hay ningún modelo registrado como '{name}'. Ejecute primero el pipeline.")
        mv = max(versions, key=lambda v: int(v.version))
        model_run = client.get_run(mv.run_id)
        pipeline_run_id = model_run.data.tags.get("mlflow.parentRunId")
        training_hash = client.get_run(pipeline_run_id).data.tags["fairgate.batch_hash"]

        df, current_hash = load_batch(domain)
        if current_hash != training_hash:
            raise MonitorError(
                f"El lote disponible ({current_hash}) no es el lote con que se entrenó el modelo "
                f"({training_hash}); no se puede reconstruir la referencia del monitor de deriva."
            )
        train, _ = split(domain, df)
        model = mlflow.sklearn.load_model(f"models:/{name}/{mv.version}")
        return cls(
            domain=domain, model=model, reference=train, training_hash=training_hash,
            pipeline_run_id=pipeline_run_id, model_run_id=mv.run_id, log_lineage=lineage.enabled(),
        )

    # ------------------------------------------------------------------ operación
    def process(self, batch: ProductionBatch) -> BatchOutcome:
        scored = score_batch(self.domain, self.contract, self.model, batch, self.pseudonymizer)
        top_k = int(self.contract.params.get("reason_top_k", 3))
        if top_k > 0:
            scored.reasons = self._reasons(scored, top_k)
        result = run_c4(self.contract, self.domain, scored, self.reference)
        result.extra["pseudonym_key"] = "efímera" if self.pseudonymizer.ephemeral else "configurada"
        if scored.reasons is not None:
            result.extra["rejections_explained"] = int(scored.reasons["pseudo_id"].nunique())
        out = BatchOutcome(scored, result, self._log(result, scored.reasons))
        self.outcomes.append(out)
        return out

    def run(self, batches: list[ProductionBatch]) -> list[BatchOutcome]:
        """Procesa todos los lotes (el C4 no detiene la operación: alerta y dispara el CT)."""
        try:
            return [self.process(b) for b in batches]
        finally:
            self.close()

    def _reasons(self, scored: ScoredBatch, top_k: int) -> pd.DataFrame:
        """Generador de razones de rechazo: recibe las mismas variables que el scorer."""
        from .explanations import rejection_reasons

        features = self.domain.dataset.features.all
        x = scored.batch.data[features].reset_index(drop=True).set_axis(scored.decisions.index)
        return rejection_reasons(self.model, x, self.reference[features], scored.decisions["decision"],
                                 self.domain.dataset.favorable_label, top_k)

    def _log(self, result: GateResult, reasons: pd.DataFrame | None = None) -> str | None:
        if not self.log_lineage:
            return None
        if self._lineage is None:
            if self.pipeline_run_id is None or self.model_run_id is None:
                raise MonitorError("Para registrar la operación se necesita la ejecución del pipeline y del modelo.")
            self._lineage = lineage.Lineage(
                self.domain.dataset.name, self.training_hash, len(self.reference), role="operacion",
                tags={"fairgate.pipeline_run_id": self.pipeline_run_id, "fairgate.model_run_id": self.model_run_id},
            )
        artifacts = None
        if reasons is not None:
            artifacts = {"rejection_reasons.json": reasons.to_json(orient="records", force_ascii=False)}
        return self._lineage.log_gate(result, artifacts=artifacts)

    def close(self) -> None:
        if self._lineage is not None:
            self._lineage.close(all(o.result.passed for o in self.outcomes))
            self._lineage = None

    @property
    def trigger_ct(self) -> bool:
        return any(o.result.extra["trigger_ct"] for o in self.outcomes)


__all__ = [
    "Monitor", "MonitorError", "ProductionBatch", "Pseudonymizer", "ScoredBatch",
    "column_drift", "data_drift", "read_batch", "run_c4", "score_batch", "simulate_batches",
]
