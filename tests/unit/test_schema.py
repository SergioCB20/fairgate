import pytest
from pydantic import ValidationError

from fairgate.data import load_domain
from fairgate.gates import check_contract, expected_cases
from fairgate.schema import Contract, ProtectedAttribute

BASE = {"contract_id": "C1", "version": "1", "gate": "QA_GATE_1", "stage": "s", "dataset": "d",
        "protected_attributes": [{"name": "z", "groups": [1, 2]}], "rules": []}


def test_use_as_feature_requires_justification():
    with pytest.raises(ValidationError, match="justificación"):
        ProtectedAttribute(name="Age_group", column="Age", groups={"a": "Age < 25", "b": "Age >= 25"},
                           source_columns=["Age"], use_as_feature=True)


def test_use_as_feature_with_justification_releases_sources():
    attr = ProtectedAttribute(name="Age_group", column="Age", groups={"a": "Age < 25", "b": "Age >= 25"},
                              source_columns=["Age"], use_as_feature=True, justification="ECOA permite ...")
    assert attr.forbidden_columns == set()


def test_forbidden_columns_include_sources_by_default():
    attr = ProtectedAttribute(name="Age_group", column="Age", groups={"a": "Age < 25", "b": "Age >= 25"},
                              source_columns=["Age"])
    assert attr.forbidden_columns == {"Age_group", "Age"}


def test_unprivileged_must_be_a_group():
    with pytest.raises(ValidationError, match="no privilegiado"):
        ProtectedAttribute(name="z", groups=[1, 2], unprivileged=3)


def test_remediation_only_in_c3():
    with pytest.raises(ValidationError, match="solo el Contrato C3"):
        Contract.model_validate({**BASE, "remediation": {"method": "reweighing"}})


def test_unknown_keys_are_rejected():
    with pytest.raises(ValidationError):
        Contract.model_validate({**BASE, "umbral_magico": 0.1})


def test_davronov_domain_is_valid_without_data():
    domain = load_domain("domains/davronov")
    assert set(domain.contracts) == {"QA_GATE_1", "QA_GATE_2", "QA_GATE_3", "QA_GATE_4"}
    for c in domain.contracts.values():
        check_contract(c, domain.dataset)
    # C3: 3 reglas de grupo x 2 atributos + guardia de exactitud = 7 pruebas
    assert len(expected_cases(domain.contracts["QA_GATE_3"])) == 13  # 3 bloqueos + 3 advertencias del IC (ADR-018), por atributo, + C3-ACC
    # C4: deriva de datos + 3 reglas de grupo x 2 atributos = 7 pruebas; alerta con el mejor extremo
    c4 = domain.contracts["QA_GATE_4"]
    assert len(expected_cases(c4)) == 7 and c4.statistics.decide_on == "best_bound"
    c3_rules = {r.metric: (r.operator, r.threshold) for r in domain.contracts["QA_GATE_3"].rules}
    assert all(c3_rules[r.metric] == (r.operator, r.threshold) for r in c4.rules if r.metric in c3_rules)
    # Ningún atributo protegido ni su columna de origen es variable del modelo (ADR-013)
    forbidden = domain.contracts["QA_GATE_1"].forbidden_columns
    assert not forbidden & set(domain.dataset.features.all)


def test_model_is_declared_in_dataset_spec():
    from fairgate.preprocessing import build_model_pipeline
    from fairgate.schema import FeatureSpec, ModelSpec

    feats = FeatureSpec(numeric=["a"])
    pipe = build_model_pipeline(feats, ModelSpec(estimator="random_forest", params={"n_estimators": 10}))
    assert type(pipe.named_steps["classifier"]).__name__ == "RandomForestClassifier"
    assert pipe.named_steps["classifier"].n_estimators == 10
    # Por defecto se mantiene la regresión logística balanceada
    default = build_model_pipeline(feats).named_steps["classifier"]
    assert type(default).__name__ == "LogisticRegression" and default.class_weight == "balanced"
    with pytest.raises(ValidationError):
        ModelSpec(estimator="svm")
