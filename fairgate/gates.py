"""Compuertas de calidad C1, C2 y C3 (Cap. 4, 4.3.4). El C4 (operación) está en `monitoring.py`."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pandera.pandas as pa
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import balanced_accuracy_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline

from . import metrics as fm
from .data import Domain, group_frame
from .preprocessing import build_model_pipeline, stepwise_outputs
from .remediation import get_technique
from .results import GateResult, RuleResult, evaluate, not_applicable
from .schema import Contract, DatasetSpec, Rule

# Métricas que admite cada compuerta; True = se evalúa por atributo protegido.
GATE_METRICS: dict[str, dict[str, bool]] = {
    "QA_GATE_1": {
        "schema_violations": False,
        "max_null_ratio": False,
        "duplicate_ratio": False,
        "forbidden_features": False,
        "max_feature_target_auc": False,
        "min_group_proportion": True,
    },
    "QA_GATE_2": {"leakage_auc": True, "leakage_auc_increment": True},
    "QA_GATE_3": {"spd": True, "eod": True, "di": True, "balanced_accuracy_drop": False},
    "QA_GATE_4": {"drift_share": False, "spd": True, "eod": True, "di": True},
}


class ContractError(Exception):
    """El contrato no es ejecutable (métrica desconocida, columna inexistente, etc.)."""


def check_contract(contract: Contract, dataset: DatasetSpec) -> None:
    allowed = GATE_METRICS.get(contract.gate)
    if allowed is None:
        raise ContractError(f"{contract.contract_id}: la compuerta {contract.gate} aún no está implementada.")
    for rule in contract.rules:
        if rule.metric not in allowed:
            raise ContractError(
                f"{contract.contract_id}/{rule.id}: la métrica '{rule.metric}' no existe en {contract.gate}. "
                f"Disponibles: {sorted(allowed)}"
            )


def per_attribute(contract: Contract, rule: Rule) -> bool:
    return GATE_METRICS[contract.gate][rule.metric]


def expected_cases(contract: Contract) -> list[tuple[str, str | None]]:
    """Combinaciones (regla, atributo) que produce el contrato: una prueba por combinación."""
    cases = []
    for rule in contract.rules:
        if per_attribute(contract, rule):
            cases += [(rule.id, a.name) for a in contract.protected_attributes]
        else:
            cases.append((rule.id, None))
    return cases


# --------------------------------------------------------------------------- C1


def _pandera_schema(dataset: DatasetSpec) -> pa.DataFrameSchema:
    dtypes = {"int": pa.Int, "float": pa.Float, "str": pa.String}
    cols = {}
    for c in dataset.columns:
        checks = []
        if c.allowed_values is not None:
            checks.append(pa.Check.isin(c.allowed_values))
        if c.min_value is not None:
            checks.append(pa.Check.ge(c.min_value))
        if c.max_value is not None:
            checks.append(pa.Check.le(c.max_value))
        cols[c.name] = pa.Column(dtypes[c.dtype], checks=checks, nullable=c.nullable, coerce=False)
    return pa.DataFrameSchema(cols, strict=False)


def run_c1(contract: Contract, domain: Domain, df: pd.DataFrame, batch_hash: str) -> GateResult:
    ds = domain.dataset
    results: list[RuleResult] = []
    groups = group_frame(df, contract.protected_attributes)
    forbidden = (contract.forbidden_columns | set(ds.leakage_columns)) & set(ds.features.all)

    for rule in contract.rules:
        if rule.metric == "schema_violations":
            try:
                _pandera_schema(ds).validate(df, lazy=True)
                n, sample = 0, []
            except pa.errors.SchemaErrors as err:
                fc = err.failure_cases
                n, sample = len(fc), fc.head(10).astype(str).to_dict("records")
            results.append(evaluate(rule, n, details={"failure_cases": sample}))
        elif rule.metric == "max_null_ratio":
            ratios = df.isna().mean()
            results.append(evaluate(rule, float(ratios.max()), details={"column": ratios.idxmax()}))
        elif rule.metric == "duplicate_ratio":
            results.append(evaluate(rule, float(df.duplicated().mean())))
        elif rule.metric == "forbidden_features":
            results.append(evaluate(rule, len(forbidden), details={"columns": sorted(forbidden)}))
        elif rule.metric == "max_feature_target_auc":
            # Fuga de la etiqueta no declarada: una variable que por sí sola casi determina Y.
            target = df[ds.target] == ds.favorable_label
            scores = {c: univariate_auc(df[c], target) for c in ds.features.all if c in df.columns}
            worst = max(scores, key=scores.get)
            suspects = {c: round(a, 4) for c, a in scores.items() if a > rule.threshold}
            results.append(evaluate(rule, scores[worst], details={"feature": worst, "suspects": suspects}))
        elif rule.metric == "min_group_proportion":
            for attr in contract.protected_attributes:
                g = groups[attr.name]
                props = g.value_counts(normalize=False) / len(g)
                props = props.reindex(attr.group_labels, fill_value=0.0)
                results.append(
                    evaluate(
                        rule,
                        float(props.min()),
                        attribute=attr.name,
                        details={"proportions": props.round(4).to_dict(), "ungrouped": int(g.isna().sum())},
                    )
                )
    return GateResult.new(contract, batch_hash, "lote", results)


# --------------------------------------------------------------------------- C2


def _as_model_input(x: pd.DataFrame, categorical: list[str]) -> pd.DataFrame:
    x = x.copy()
    for c in categorical:
        if c in x.columns:
            x[c] = x[c].astype("category")
    return x


def leakage_auc(
    x: pd.DataFrame, z: pd.Series, y: pd.Series, categorical: list[str], folds: int, random_state: int
) -> float:
    """L = Σ_y P(Y=y) · AUC(Z | X, Y=y), con predicciones fuera de la muestra (validación cruzada)."""
    x = _as_model_input(x, categorical)
    total, weight_sum = 0.0, 0.0
    for yv in y.unique():
        mask = (y == yv).to_numpy()
        zs = z[mask].astype(str)
        if zs.nunique() < 2 or zs.value_counts().min() < folds:
            continue
        clf = HistGradientBoostingClassifier(max_iter=100, random_state=random_state)
        cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=random_state)
        proba = cross_val_predict(clf, x[mask], zs, cv=cv, method="predict_proba")
        classes = np.sort(zs.unique())
        if len(classes) == 2:
            auc = roc_auc_score(zs == classes[1], proba[:, 1])
        else:
            auc = roc_auc_score(zs, proba, multi_class="ovr", average="macro", labels=classes)
        w = mask.mean()
        total += w * auc
        weight_sum += w
    return total / weight_sum if weight_sum else float("nan")


def univariate_auc(v: pd.Series, target: pd.Series, max_categories: int = 30) -> float:
    """AUC de una sola variable para separar `target` (0,5 = nada; 1 = separa por completo).

    Las variables categóricas o de pocos valores se codifican por la tasa de `target` de
    cada categoría. Se toma max(AUC, 1 - AUC) porque interesa la separación, no su sentido.
    """
    target = target.astype(bool)
    if not pd.api.types.is_numeric_dtype(v) or v.nunique() <= max_categories:
        v = v.map(target.groupby(v).mean())
    v = pd.to_numeric(v, errors="coerce")
    v = v.fillna(v.median() if v.notna().any() else 0)
    if v.nunique() < 2 or target.nunique() < 2:
        return 0.5
    auc = roc_auc_score(target, v)
    return float(max(auc, 1 - auc))


def top_proxies(x: pd.DataFrame, z: pd.Series, k: int = 3) -> list[dict]:
    """Variables que más separan los grupos por sí solas (AUC univariado, para localizar)."""
    zs = z.astype(str)
    target = zs == zs.value_counts().index[-1]
    scores = [{"feature": c, "auc": round(univariate_auc(x[c], target), 4)} for c in x.columns]
    return sorted(scores, key=lambda s: -s["auc"])[:k]


def run_c2(
    contract: Contract,
    domain: Domain,
    train: pd.DataFrame,
    batch_hash: str,
    steps: list[tuple[str, pd.DataFrame]] | None = None,
) -> GateResult:
    """`steps`: salida de cada paso del preprocesamiento; por defecto, la de `stepwise_outputs`.
    Permite evaluar otros transformadores (p. ej., uno sesgado en el escenario E3 del O4)."""
    ds = domain.dataset
    folds = int(contract.params.get("folds", 5))
    rs = int(contract.params.get("random_state", 42))
    steps = stepwise_outputs(train, ds.features) if steps is None else steps
    groups = group_frame(train, contract.protected_attributes)
    y = train[ds.target]

    per_attr: dict[str, list[dict]] = {}
    for attr in contract.protected_attributes:
        z = groups[attr.name]
        keep = z.notna()
        allowed_sources = set(attr.source_columns) | {attr.value_column} if attr.use_as_feature else set()
        series = []
        for step, x in steps:
            cols = [c for c in x.columns if not any(c == s or c.startswith(f"{s}_") for s in allowed_sources)]
            xs = x.loc[keep, cols]
            cat = [c for c in ds.features.categorical if c in cols and step != "codificacion"]
            L = leakage_auc(xs, z[keep], y[keep], cat, folds, rs)
            series.append({"step": step, "L": round(L, 4), "top_proxies": top_proxies(xs, z[keep])})
        per_attr[attr.name] = series

    results: list[RuleResult] = []
    for rule in contract.rules:
        for attr in contract.protected_attributes:
            series = per_attr[attr.name]
            if rule.metric == "leakage_auc":
                # Valor: la mayor filtración observada. Paso: el primero que supera el umbral
                # (donde aparece la filtración); si ninguno lo supera, el de mayor filtración.
                worst = max(series, key=lambda s: s["L"])
                first = next((s for s in series if s["L"] > rule.threshold), worst)
                value, step = worst["L"], first["step"]
            else:  # leakage_auc_increment
                incs = [(series[k]["L"] - series[k - 1]["L"], series[k]["step"]) for k in range(1, len(series))]
                value, step = max(incs) if incs else (0.0, None)
            res = evaluate(rule, value, attribute=attr.name, details={"step": step, "by_step": series})
            results.append(res)
    return GateResult.new(contract, batch_hash, "pasos", results)


# --------------------------------------------------------------------------- C3


@dataclass
class ModelEvaluation:
    subject: str
    model: Pipeline
    balanced_accuracy: float
    result: GateResult
    extra: dict = field(default_factory=dict)


def group_fairness_results(
    contract: Contract, rule: Rule, y_true: np.ndarray, y_pred: np.ndarray, groups: pd.DataFrame
) -> list[RuleResult]:
    """Una regla de equidad de grupo (SPD, EOD o DI) por atributo protegido, con su intervalo
    (ADR-008). La usan el C3 sobre el conjunto de prueba y el C4 sobre cada lote de producción."""
    st = contract.statistics
    results = []
    for attr in contract.protected_attributes:
        yt, yp, g = fm.drop_ungrouped(y_true, y_pred, groups[attr.name].to_numpy())
        u = None if attr.unprivileged is None else str(attr.unprivileged)
        if st.method == "bootstrap":
            value, ci, rates = fm.fairness_metric_with_ci(
                rule.metric, yt, yp, g, u, st.n_resamples, st.confidence, st.random_state
            )
        else:
            value, ci = fm.fairness_metric(rule.metric, yt, yp, g, u), None
            sel, tpr = fm.group_rates(yt, yp, g, u)
            rates = {"selection_rate": sel, "tpr": tpr}
        form = "direccional" if u is not None else "simétrica"
        counts = pd.Series(g).value_counts().to_dict()
        results.append(
            evaluate(rule, value, attribute=attr.name, ci=ci, decide_on=rule.decide_on or st.decide_on,
                     details={"form": form, **rates, "group_sizes": {str(k): int(v) for k, v in counts.items()}})
        )
    return results


def _evaluate_model(
    contract: Contract,
    domain: Domain,
    model: Pipeline,
    test: pd.DataFrame,
    batch_hash: str,
    subject: str,
    base_bal_acc: float | None = None,
) -> tuple[GateResult, float]:
    ds = domain.dataset
    y_true = (test[ds.target] == ds.favorable_label).astype(int).to_numpy()
    y_pred = (model.predict(test[ds.features.all]) == ds.favorable_label).astype(int)
    bal_acc = float(balanced_accuracy_score(y_true, y_pred))
    groups = group_frame(test, contract.protected_attributes)

    results: list[RuleResult] = []
    for rule in contract.rules:
        if rule.metric == "balanced_accuracy_drop":
            if base_bal_acc is None:
                results.append(not_applicable(rule, reason="solo se evalúa sobre el modelo remediado"))
            else:
                results.append(evaluate(rule, base_bal_acc - bal_acc, details={"base": base_bal_acc, "remediado": bal_acc}))
            continue
        results += group_fairness_results(contract, rule, y_true, y_pred, groups)
    res = GateResult.new(contract, batch_hash, subject, results, balanced_accuracy=bal_acc)
    return res, bal_acc


def run_c3(contract: Contract, domain: Domain, train: pd.DataFrame, test: pd.DataFrame, batch_hash: str):
    """Evalúa el modelo base y, si incumple una regla 'block', aplica la remediación declarada."""
    ds = domain.dataset
    x_train, y_train = train[ds.features.all], train[ds.target]
    base = build_model_pipeline(ds.features, ds.model, random_state=ds.split.random_state)
    base.fit(x_train, y_train)
    base_res, base_acc = _evaluate_model(contract, domain, base, test, batch_hash, "modelo:base")
    evaluations = [ModelEvaluation("modelo:base", base, base_acc, base_res)]

    rem = contract.remediation
    if not base_res.passed and rem is not None and rem.enabled:
        tech = get_technique(rem.method, rem.allow_protected_at_inference)
        # Los registros que no pertenecen a ningún grupo (p. ej., solicitudes conjuntas en HMDA)
        # forman su propio estrato en la reponderación.
        groups_train = group_frame(train, contract.protected_attributes).fillna("sin grupo")
        combo = groups_train.astype(str).agg("|".join, axis=1)
        model, report = tech.apply(base, x_train, y_train, combo, **rem.params)
        rem_res, rem_acc = _evaluate_model(
            contract, domain, model, test, batch_hash, "modelo:remediado", base_bal_acc=base_acc
        )
        rem_res.extra.update({"remediation": tech.name, "reference": tech.reference, "report": report})
        evaluations.append(ModelEvaluation("modelo:remediado", model, rem_acc, rem_res, report))
    return evaluations
