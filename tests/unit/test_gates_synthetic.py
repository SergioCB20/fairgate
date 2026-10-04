"""Casos positivos y negativos de las compuertas con dominios sintéticos."""
from fairgate.engine import Session

from .conftest import synthetic_frame, write_domain


def test_c1_blocks_underrepresented_group_and_stops_pipeline(tmp_path):
    dom = write_domain(tmp_path, synthetic_frame(minority=0.02))
    session = Session(dom)
    outcomes = session.run()
    assert [o.gate for o in outcomes] == ["QA_GATE_1"]  # el pipeline se detiene en C1
    rep = outcomes[0].final.find("C1-REP", "z")
    assert not rep.passed and rep.value < 0.05


def test_c1_blocks_protected_source_column_as_feature(tmp_path):
    dom = write_domain(tmp_path, synthetic_frame(), numeric=("x1", "z"))
    res = Session(dom).outcome("QA_GATE_1").final
    forbidden = res.find("C1-FORBIDDEN", None)
    assert not forbidden.passed and forbidden.details["columns"] == ["z"]


def test_c2_detects_proxy_and_reports_it(tmp_path):
    dom = write_domain(tmp_path, synthetic_frame(proxy_strength=0.9), categorical=("c1", "p"))
    res = Session(dom).outcome("QA_GATE_2").final
    auc = res.find("C2-AUC", "z")
    assert not auc.passed and auc.value > 0.8
    proxies = [p["feature"] for p in auc.details["by_step"][0]["top_proxies"]]
    assert proxies[0] == "p"


def test_c2_passes_without_proxy(tmp_path):
    dom = write_domain(tmp_path, synthetic_frame(proxy_strength=0.0))
    res = Session(dom).outcome("QA_GATE_2").final
    assert res.find("C2-AUC", "z").passed


def test_c3_remediation_is_recorded(tmp_path):
    # Etiqueta muy dependiente del grupo -> el modelo base incumple la SPD
    df = synthetic_frame(n=3000, bias=2.5)
    df["x1"] = df["x1"] + 1.2 * (df["z"] == 2)  # x1 correlacionada con el grupo
    dom = write_domain(tmp_path, df)
    out = Session(dom).outcome("QA_GATE_3")
    assert [r.subject for r in out.results] == ["modelo:base", "modelo:remediado"]
    base, rem = out.results
    assert not base.passed
    # El motor garantiza que la remediación se aplica, se registra y se reevalúa con las
    # mismas reglas; NO garantiza que la reponderación baste (ADR-012): aquí el grupo
    # influye solo a través de x1 y el remediado sigue incumpliendo -> la compuerta bloquea.
    assert rem.find("C3-SPD", "z").applicable
    assert out.passed == rem.passed
    assert rem.extra["remediation"] == "reweighing"
    assert rem.extra["report"]["cell_sizes"]
    assert base.find("C3-ACC", None).applicable is False
    assert rem.find("C3-ACC", None).applicable is True


def test_c3_without_remediation_blocks(tmp_path):
    df = synthetic_frame(n=3000, bias=2.5)
    df["x1"] = df["x1"] + 1.2 * (df["z"] == 2)
    dom = write_domain(tmp_path, df, c3_remediation=False)
    out = Session(dom).outcome("QA_GATE_3")
    assert len(out.results) == 1 and not out.passed
