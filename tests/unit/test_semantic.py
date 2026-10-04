"""Zona 4 de punta a punta con dominios sintéticos: MLflow → RDF → SHACL → SPARQL → reporte."""
import pytest
from rdflib import Literal, Namespace

from fairgate.engine import Session
from fairgate.semantic.export import FAIR, build_graph, load_pipeline_run, validate
from fairgate.semantic.queries import run_query
from fairgate.semantic.report import add_report_node, write_pdf

from .conftest import synthetic_frame, write_domain


@pytest.fixture
def mlflow_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("FAIRGATE_LINEAGE", "1")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}")
    monkeypatch.setenv("MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR", "false")
    monkeypatch.chdir(tmp_path)  # los artefactos de MLflow se escriben en el directorio temporal
    return tmp_path


def _graph_for(dom, gates=None):
    s = Session(dom)
    if gates is None:
        s.run()  # se detiene en la primera compuerta que bloquea
    else:
        for gate in gates:
            s.outcome(gate)
        s.close()
    run = load_pipeline_run("sint")
    return run, build_graph(run)


def test_blocked_pipeline_graph_conforms_and_pc1_finds_the_rule(tmp_path, mlflow_tmp):
    dom = write_domain(tmp_path, synthetic_frame(proxy_strength=0.9), categorical=("c1", "p"))
    run, g = _graph_for(dom)
    conforms, text = validate(g)
    assert conforms, text
    assert [gate["result"]["contract_id"] for gate in run.gates] == ["C1", "C2"]  # se detuvo en C2
    pc1 = run_query(g, "PC1")
    assert {(r["contractId"], r["ruleId"], r["attribute"]) for r in pc1} == {("C2", "C2-AUC", "z")}
    assert pc1[0]["step"] == "entrada"  # paso donde se observó la filtración
    assert run_query(g, "PC2") == []  # ningún modelo aprobado


def test_remediation_is_traceable_pc5(tmp_path, mlflow_tmp):
    df = synthetic_frame(n=3000, bias=2.5)
    df["x1"] = df["x1"] + 1.2 * (df["z"] == 2)
    dom = write_domain(tmp_path, df)
    # x1 está correlacionada con z, así que el C2 bloquearía: se ejecuta el C3 directamente.
    run, g = _graph_for(dom, gates=["QA_GATE_3"])
    assert validate(g)[0]
    pc5 = run_query(g, "PC5")
    assert {r["ruleId"] for r in pc5} == {"C3-SPD"}  # C3-ACC no aplica al modelo base
    assert pc5[0]["method"] == "reweighing"
    assert pc5[0]["baseAcc"] is not None and pc5[0]["remAcc"] is not None


def test_shacl_rejects_incomplete_execution(tmp_path, mlflow_tmp):
    dom = write_domain(tmp_path, synthetic_frame())
    _, g = _graph_for(dom)
    execution = next(g.subjects(predicate=FAIR.gatePassed))
    g.remove((execution, FAIR.gatePassed, None))  # ejecución sin resultado
    conforms, _ = validate(g)
    assert not conforms


def test_report_is_generated_from_the_graph(tmp_path, mlflow_tmp):
    dom = write_domain(tmp_path, synthetic_frame())
    run, g = _graph_for(dom)
    add_report_node(g, run)
    assert validate(g)[0]
    pdf = write_pdf(g, run, True, tmp_path / "reporte.pdf")
    assert pdf.exists() and pdf.stat().st_size > 1000


def test_operation_alerts_are_traceable_pc4(tmp_path, mlflow_tmp):
    from fairgate.monitoring import Monitor, ProductionBatch, simulate_batches

    dom = write_domain(tmp_path, synthetic_frame(n=4000))
    assert all(o.passed for o in Session(dom).run())  # modelo aprobado y registrado (Trigger CD)
    monitor = Monitor.from_registry(dom)  # lo carga del registro de modelos de MLflow
    biased = synthetic_frame(n=600, seed=7)
    biased.loc[biased["z"] == 2, "x1"] += 1.5
    monitor.run([*simulate_batches(synthetic_frame(n=600, seed=3), 1), ProductionBatch("sesgado", biased)])

    run = load_pipeline_run("sint")
    assert [len(op["gates"]) for op in run.operations] == [2]
    g = build_graph(run)
    conforms, text = validate(g)
    assert conforms, text
    pc4 = run_query(g, "PC4")
    assert {(r["alertType"], r["subject"]) for r in pc4} == {("datos", "lote:sesgado"), ("sesgo", "lote:sesgado")}
    sesgo = next(r for r in pc4 if r["alertType"] == "sesgo")
    assert sesgo["trigger"] is True and "C4-SPD[z]" in sesgo["rules"]
    # Los lotes de producción quedan en el grafo junto al lote de entrenamiento
    assert len(set(g.subjects(predicate=FAIR.dvcHash))) == 3
    add_report_node(g, run)
    assert validate(g)[0]
    assert write_pdf(g, run, True, tmp_path / "reporte.pdf").exists()


def test_shacl_rejects_alert_without_batch(tmp_path, mlflow_tmp):
    from fairgate.monitoring import Monitor, ProductionBatch

    dom = write_domain(tmp_path, synthetic_frame(n=4000))
    Session(dom).run()
    biased = synthetic_frame(n=600, seed=7)
    biased.loc[biased["z"] == 2, "x1"] += 1.5
    Monitor.from_registry(dom).run([ProductionBatch("sesgado", biased)])
    g = build_graph(load_pipeline_run("sint"))
    alert = next(g.subjects(predicate=FAIR.alertType))
    g.remove((alert, FAIR.raisedOn, None))
    assert not validate(g)[0]
