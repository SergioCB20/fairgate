"""Infraestructura del O4 (experiments/) con un dominio sintético."""
import json

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from experiments import analysis, audit, configs, runner, scenarios, stats
from experiments.protocol import Expected, Protocol
from fairgate.data import load_batch, load_domain

from .conftest import synthetic_frame, write_domain


@pytest.fixture
def proto(tmp_path):
    dom = write_domain(tmp_path, synthetic_frame(n=2000, bias=0.3), categorical=("c1",))
    return Protocol(domain=str(dom), age_attr="z", age_group="1", sex_attr="z", e3_column="x1",
                    e1_proportions=(0.06, 0.02), e2_coincidence=(0.9,), e3_missing=(0.2,), e4_flip=(0.3,),
                    e5_disparity=(0.0, 0.3), e5_lot_sizes=(200, 400), default_batches=2)


@pytest.fixture
def base(proto):
    domain = load_domain(proto.domain)
    df, _ = load_batch(domain)
    return domain, df


# --------------------------------------------------------------------------- inyectores


def test_underrepresent_reaches_the_proportion():
    df = synthetic_frame(n=4000)
    out, info = scenarios.underrepresent(df, df["z"] == 1, 0.04, np.random.default_rng(0))
    assert abs((out["z"] == 1).mean() - 0.04) < 0.002
    assert (out["z"] == 2).sum() == (df["z"] == 2).sum()  # el resto no se toca
    assert info["proportion"] == pytest.approx((out["z"] == 1).mean())


def test_proxy_coincides_in_the_given_fraction():
    z = pd.Series(np.random.default_rng(0).choice([1, 2], 5000))
    p = scenarios.proxy_column(z, [1, 2], 0.75, np.random.default_rng(1))
    assert abs((p == z).mean() - 0.75) < 0.02
    assert set(p.unique()) <= {1, 2}


def test_flip_labels_only_good_payers_of_the_group():
    df = synthetic_frame(n=3000)
    out, info = scenarios.flip_labels(df, df["z"] == 1, "y", 1, 0.3, np.random.default_rng(0))
    changed = df["y"] != out["y"]
    assert changed.sum() == info["flipped"] == round(0.3 * ((df["z"] == 1) & (df["y"] == 1)).sum())
    assert (df.loc[changed, "z"] == 1).all() and (df.loc[changed, "y"] == 1).all()


def test_biased_imputation_depends_on_the_group():
    df = scenarios.inject_missing(synthetic_frame(n=1000), "x1", 0.2, np.random.default_rng(0))
    out = scenarios.biased_impute(df, "x1", df["z"].astype(str), {"1": 9.0, "2": -9.0})
    imputed = df["x1"].isna()
    assert imputed.sum() == 200 and not out["x1"].isna().any()
    assert (out.loc[imputed & (df["z"] == 1), "x1"] == 9.0).all()
    assert (out.loc[imputed & (df["z"] == 2), "x1"] == -9.0).all()


def test_induce_disparity_reaches_the_target():
    df = synthetic_frame(n=4000)
    model = LogisticRegression().fit(df[["x1"]], df["y"])
    pool = df[model.predict(df[["x1"]]) == 0]
    mask = df["z"] == 1
    out, info = scenarios.induce_disparity(df, mask, model, ["x1"], pool, 1, 0.20, np.random.default_rng(0))
    approved = model.predict(out[["x1"]]) == 1
    assert approved[~mask.to_numpy()].mean() - approved[mask.to_numpy()].mean() == pytest.approx(0.20, abs=0.01)
    assert info["shifted"] > 0


# --------------------------------------------------------------------------- repeticiones


def test_development_repetition_records_every_gate(proto, base):
    rep = runner.run_development(proto, *base, "E3", 0.2, seed=1)
    rec = json.loads(json.dumps(rep.record))  # serializable
    assert set(rec["gates"]) == {"C1", "C2", "C3", "C4"}
    assert len(rec["gates"]["C4"]["batches"]) == proto.default_batches
    c2 = next(r for r in rec["gates"]["C2"]["rules"] if r["rule_id"] == "C2-AUC")
    assert [s["step"] for s in c2["by_step"]] == ["entrada", "imputacion", "escalado", "codificacion"]
    inc = c2["by_step"][1]["L"] - c2["by_step"][0]["L"]
    assert inc > 0.05  # el transformador sesgado introduce la filtración en la imputación
    assert rec["gates"]["C3"]["utility"]["base"]["auroc"] > 0.5


def test_e2_adds_the_proxy_as_a_model_variable(proto, base):
    rep = runner.run_development(proto, *base, "E2", 0.9, seed=1)
    assert proto.proxy_column in rep.prepared.domain.dataset.features.all
    out = configs.outcome(rep.record, "P", proto)
    assert out["first_gate"] == "C2" and out["localized"]


def test_e4_triggers_c3_and_remediation(proto, base):
    rep = runner.run_development(proto, *base, "E4", 0.3, seed=1)
    c3 = rep.record["gates"]["C3"]
    assert c3["blocked"] and "remediation" in c3
    assert "remediado" in c3["utility"]


def test_campaign_is_resumable_and_analysis_runs(proto, tmp_path):
    out = tmp_path / "r.jsonl"
    n = runner.campaign(proto, [1], ["E0", "E5"], out, audit=True, log=lambda m: None)
    assert n == 1 + len(proto.intensities("E5"))
    assert runner.campaign(proto, [1], ["E0", "E5"], out, log=lambda m: None) == 0
    records = analysis.load(out)
    assert all(r["audit"]["conforms"] for r in records)
    assert all(all(r["audit"]["fidelity"].values()) for r in records)
    text = analysis.report(records, proto, "prueba")
    assert "Falsos positivos" in text and "Lote mínimo" in text


# --------------------------------------------------------------------------- configuraciones


def _record(c1=False, c2=False, c3=False, c4=(False,), scenario="E1", intensity=0.02, c2_step=None):
    def gate(blocked, rule):
        r = {"rule_id": rule, "key": rule, "severity": "block", "applicable": True, "passed": not blocked}
        if c2_step and rule.startswith("C2"):
            r["step"] = c2_step
        return {"blocked": blocked, "rules": [r], "seconds": 1.0}

    batches = [{"blocked": b, "rules": [{"rule_id": "C4-SPD", "severity": "block", "applicable": True,
                                         "passed": not b}], "seconds": 0.5} for b in c4]
    return {"scenario": scenario, "intensity": intensity, "gates": {
        "C1": gate(c1, "C1-REP"), "C2": gate(c2, "C2-INC"), "C3": gate(c3, "C3-SPD"),
        "C4": {"batches": batches, "first_alert_batch": next((i for i, b in enumerate(c4, 1) if b), None)}}}


def test_configs_combine_only_their_gates(proto):
    rec = _record(c1=True, c3=True)
    out = configs.outcomes(rec, proto)
    assert out["P"]["first_gate"] == "C1" and out["P"]["localized"]  # E1 al 2 %: C1-REP
    assert out["P-C1"]["first_gate"] == "C3" and out["P-C1"]["localized"] is False
    assert out["B0"]["first_gate"] == "C3"
    assert out["P"]["seconds_to_block"] == 1.0 and out["P-C1"]["seconds_to_block"] == 2.0


def test_c4_time_counts_batches(proto):
    rec = _record(c4=(False, True), scenario="E5", intensity=[0.3, 200])
    o = configs.outcome(rec, "B2", proto)
    assert o["first_gate"] == "C4" and o["batches_to_alert"] == 2 and o["localized"]
    assert o["seconds_to_block"] == 2.0  # C3 (1 s) + dos lotes (0,5 s cada uno)


def test_expected_follows_table_20(proto):
    assert proto.expected("E1", 0.06) == Expected(None)
    assert proto.expected("E1", 0.04).gate == "C1"
    assert proto.expected("E5", (0.10, 435)) == Expected(None)
    assert proto.expected("E3", 0.1).gate == "C1" and proto.secondary("E3").step == "imputacion"
    assert proto.expected("E4R", 0.3).gate == "C2" and proto.secondary("E4R").gate == "C3"
    assert analysis.confirmatory("E5", (0.3, 435), proto) and not analysis.confirmatory("E5", (0.3, 200), proto)
    assert analysis.confirmatory("E1", 0.02, proto) and not analysis.confirmatory("E1", 0.06, proto)
    assert analysis.confirmatory("E3", 0.2, proto) and proto.strongest("E2") == 0.9


def test_e4r_gives_the_label_bias_a_route(proto, base):
    rep = runner.run_development(proto, *base, "E4R", 0.3, seed=1)
    assert proto.age_proxy_column in rep.prepared.domain.dataset.features.all
    assert configs.secondary_localized(rep.record, proto) is not None


# --------------------------------------------------------------------------- estadística


def test_wilson_matches_known_values():
    lo, hi = stats.wilson(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3) and hi == pytest.approx(0.9433, abs=1e-3)


def test_mcnemar_and_holm():
    r = stats.mcnemar_exact([True] * 10 + [False] * 10, [False] * 10 + [False] * 10)
    assert r["only_a"] == 10 and r["p"] == pytest.approx(2 * 0.5**10)
    adj = stats.holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj == {"a": 0.03, "c": 0.06, "b": 0.06}


# --------------------------------------------------------------------------- auditabilidad


def test_negative_graphs_are_rejected(proto, base):
    rep = runner.run_development(proto, *base, "E4", 0.3, seed=2)
    g = audit.build_graph(audit.pipeline_run(rep))
    assert audit.validate(g)[0]
    neg = audit.negative_tests(g)
    assert len(neg) == 8 and all(neg.values())


def test_lineage_fidelity_against_mlflow(proto, base, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR", "false")
    rep = runner.run_development(proto, *base, "E0", None, seed=3)
    uri = f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"
    fid = audit.lineage_fidelity("sint", audit.log_repetition(rep, uri), uri)
    assert fid["ok"], fid["issues"]
    expected = sum(len(v) for v in rep.results.values())  # C1, C2, C3 (base y remediado) y lotes del C4
    assert fid["executions_mlflow"] == expected and fid["values_checked"] > 10


# --------------------------------------------------------------------------- E6 (HMDA)


def test_hmda_clean_maps_the_regulator_format():
    from experiments.hmda import NA, clean

    raw = pd.DataFrame({
        "action_taken": [1, 3, 1], "derived_sex": ["Male", "Sex Not Available", "Joint"],
        "derived_race": ["White", "Black or African American", "Race Not Available"],
        "applicant_age": ["<25", "8888", ">74"], "loan_amount": [105000, 55000, 1000],
        "income": [60, None, 10], "loan_to_value_ratio": ["80.5", None, "Exempt"],
        "property_value": ["125000", "70000", "Exempt"], "loan_term": ["360", "240", "Exempt"],
        "tract_minority_population_percent": [10.0, 80.0, 5.0],
        "debt_to_income_ratio": ["20%-<30%", "44", None], "loan_type": [1, 2, 1], "loan_purpose": [1, 32, 1],
        "lien_status": [1, 1, 2], "occupancy_type": [1, 1, 1], "open-end_line_of_credit": [2, 2, 1111],
        "business_or_commercial_purpose": [2, 2, 1111], "conforming_loan_limit": ["C", None, "C"],
        "county_code": [10001.0, None, 10003.0], "interest_rate": ["6.5", None, "Exempt"],
        "rate_spread": ["0.5", None, "Exempt"], "total_loan_costs": ["3000", None, "Exempt"],
        "purchaser_type": [1, 0, 0], "hoepa_status": [2, 3, 3], "denial_reason-1": [10, 1, 1111],
    })
    out = clean(raw)
    assert len(out) == 2  # el registro "Exempt" se descarta
    assert out["label"].tolist() == [1, 0]
    assert out["Sex"].tolist() == ["Male", NA] and out["Race"].tolist() == ["White", "Black"]
    assert out["Age"].tolist() == ["<25", NA]
    assert out["debt_to_income_ratio"].tolist() == ["20%-<30%", "36%-<50%"]  # 36–49 % se publica exacto
    assert out["loan_amount"].tolist() == [105.0, 55.0] and out["county_code"].tolist() == [10001, 0]


def test_freeze_is_per_domain():
    from experiments.__main__ import FREEZE, freeze_path

    assert freeze_path("domains/davronov") == FREEZE
    assert freeze_path("domains/hmda").name == "congelamiento-hmda.json"


def test_remediation_keeps_records_without_group(tmp_path):
    """Registros fuera de todo grupo (p. ej., solicitudes conjuntas en HMDA) no rompen la reponderación."""
    from fairgate.gates import run_c3

    df = synthetic_frame(n=2000, proxy_strength=0.9, bias=1.5)  # p da ruta al sesgo hacia el modelo
    df.loc[df.sample(frac=0.2, random_state=0).index, "z"] = 3  # 3: fuera de los grupos declarados
    dom = load_domain(write_domain(tmp_path, df, categorical=("c1", "p")))
    train, test = df.iloc[:1500], df.iloc[1500:]
    evals = run_c3(dom.contracts["QA_GATE_3"], dom, train, test, "h")
    assert len(evals) == 2  # el sesgo activa la remediación y esta se ejecuta
