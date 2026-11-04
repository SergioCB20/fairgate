"""Zona 4 de punta a punta con dominios sintéticos: MLflow → RDF → SHACL → SPARQL → reporte."""
import pytest
from rdflib import Literal, Namespace

from fairgate.engine import Session
from fairgate.semantic.export import FAIR, build_graph, load_pipeline_run, validate
from fairgate.semantic.queries import run_query
from fairgate.semantic.report import add_report_node, build_story, latest_executions, load_labels, write_pdf

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


def _story_text(story) -> str:
    """Texto de los párrafos y las celdas del reporte, sin marcado."""
    parts = []
    for item in story:
        if hasattr(item, "getPlainText"):
            parts.append(item.getPlainText())
        for row in getattr(item, "_cellvalues", []):
            parts += [c.getPlainText() for c in row if hasattr(c, "getPlainText")]
    return "\n".join(parts)


def test_report_is_in_spanish_even_with_remediation(tmp_path, mlflow_tmp):
    df = synthetic_frame(n=3000, bias=2.5)
    df["x1"] = df["x1"] + 1.2 * (df["z"] == 2)
    dom = write_domain(tmp_path, df)
    run, g = _graph_for(dom, gates=["QA_GATE_3"])
    text = _story_text(build_story(g, run, True, None))
    assert "Reponderación" in text and "Bloqueante" in text and "≤" in text
    for english in ("reweighing", "block", "warn", "modelo:base"):
        assert english not in text, english
    assert " le " not in text and " ge " not in text
    assert "0,10" in text  # coma decimal
    # El modelo base falla; si el remediado aprueba, el pipeline queda aprobado por la remediación.
    base = next(g.subjects(FAIR.subject, Literal("modelo:base")))
    remediated = next(g.subjects(FAIR.subject, Literal("modelo:remediado")))
    g.set((base, FAIR.gatePassed, Literal(False)))
    g.set((remediated, FAIR.gatePassed, Literal(True)))
    text = _story_text(build_story(g, run, True, None))
    assert "Cumple tras remediación" in text and "APROBADO" in text and "DETENIDO" not in text


def test_report_shows_only_the_last_monitor_run_of_each_batch(tmp_path, mlflow_tmp, monkeypatch):
    from fairgate.monitoring import PSEUDONYM_KEY_ENV, Monitor, simulate_batches

    monkeypatch.delenv(PSEUDONYM_KEY_ENV, raising=False)
    dom = write_domain(tmp_path, synthetic_frame(n=4000))
    assert all(o.passed for o in Session(dom).run())
    batches = simulate_batches(synthetic_frame(n=600, seed=3), 1)
    Monitor.from_registry(dom).run(batches)
    Monitor.from_registry(dom).run(batches)  # misma evaluación, con otra clave efímera

    run = load_pipeline_run("sint")
    g = build_graph(run)
    assert validate(g)[0]
    meds = run_query(g, "MEDICIONES")
    assert len(latest_executions(meds)) == len({(m["contractId"], m["subject"], m["timestamp"]) for m in meds}) - 1

    reasons = run_query(g, "RAZONES")
    last = max(r["time"] for r in reasons)
    shown = {r["applicant"] for r in reasons if r["time"] == last}
    hidden = {r["applicant"] for r in reasons} - shown
    assert shown and hidden  # con clave efímera, cada ejecución genera otros seudónimos

    labels = {"variables": {"x1": "Variable uno"}, "notas": ["Nota de prueba"]}
    text = _story_text(build_story(g, run, True, labels))
    assert all(a in text for a in shown) and not any(a in text for a in hidden)
    assert "se omite 1 ejecución anterior" in text
    assert "clave de seudónimos efímera" in text and "Nota de prueba" in text
    assert "Variable uno" in text and "x1 (" not in text
    assert write_pdf(g, run, True, tmp_path / "reporte.pdf", labels=labels).stat().st_size > 1000


def test_load_labels_is_optional_and_reads_the_case_file(tmp_path):
    assert load_labels(tmp_path) == {"variables": {}, "notas": []}
    (tmp_path / "reporte").mkdir()
    (tmp_path / "reporte" / "etiquetas.yaml").write_text("variables: {a: Etiqueta}\n", encoding="utf-8")
    assert load_labels(tmp_path) == {"variables": {"a": "Etiqueta"}, "notas": []}


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
    # PC3: las razones de rechazo de cada lote quedan en el grafo, ligadas al modelo que decidió
    pc3 = run_query(g, "PC3")
    rejected = {pid for o in monitor.outcomes for pid in o.scored.decisions.query("decision == 0").index}
    assert pc3 and {r["applicant"] for r in pc3} <= rejected
    assert {r["modelRun"] for r in pc3} == {monitor.model_run_id}
    assert {r["feature"] for r in pc3} <= {"x1", "c1"}
    # Los lotes de producción quedan en el grafo junto al lote de entrenamiento
    assert len(set(g.subjects(predicate=FAIR.dvcHash))) == 3
    add_report_node(g, run)
    assert validate(g)[0]
    assert write_pdf(g, run, True, tmp_path / "reporte.pdf").exists()


def test_repository_keeps_the_history_of_runs(tmp_path, mlflow_tmp):
    from fairgate.semantic.export import export
    from fairgate.semantic.store import Repository

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    blocked = write_domain(tmp_path / "a", synthetic_frame(proxy_strength=0.9), categorical=("c1", "p"))
    approved = write_domain(tmp_path / "b", synthetic_frame(n=4000))
    repo = Repository(tmp_path / "lineage")
    paths = []
    for dom in (blocked, approved):
        Session(dom).run()
        *_, conforms, _, path = export("sint", repo.directory)
        assert conforms
        paths.append(path)

    assert repo.runs("sint") == paths  # una ejecución por grafo, en orden
    pc1 = repo.query("PC1", "sint")
    assert {(r["ejecucion"], r["ruleId"]) for r in pc1} == {(paths[0].stem, "C2-AUC")}  # solo la primera bloqueó
    pc2 = repo.query("PC2", "sint")
    assert [r["ejecucion"] for r in pc2] == [paths[1].stem]  # solo la segunda aprobó un modelo
    # La unión integra los nodos compartidos: ambas ejecuciones usan el mismo contrato C1.
    union = repo.dataset("sint")
    assert len(set(union.subjects(predicate=FAIR.contractId, object=Literal("C1")))) == 1
    assert len(set(union.subjects(predicate=FAIR.gatePassed))) == 5  # C1 y C2 + C1, C2 y C3


def test_shacl_rejects_reason_without_model(tmp_path, mlflow_tmp):
    from fairgate.monitoring import Monitor, simulate_batches

    dom = write_domain(tmp_path, synthetic_frame(n=4000))
    Session(dom).run()
    Monitor.from_registry(dom).run(simulate_batches(synthetic_frame(n=600, seed=3), 1))
    g = build_graph(load_pipeline_run("sint"))
    assert validate(g)[0]
    reason = next(g.subjects(predicate=FAIR.applicantPseudoId))
    g.remove((reason, FAIR.explainsDecisionOf, None))  # razón que no indica qué modelo decidió
    assert not validate(g)[0]


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
