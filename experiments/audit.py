"""Evaluación de la auditabilidad (Cap. 6, 6.4).

1. Conformidad: el grafo de cada repetición conforma las formas SHACL.
2. Pruebas negativas: grafos alterados a propósito deben ser rechazados por el validador.
3. Completitud y exactitud del linaje: el grafo exportado desde MLflow se compara con lo que
   MLflow registró (parámetros y métricas), que actúa como verdad de referencia.
4. Preguntas de competencia: las respuestas del grafo se comparan con lo que ocurrió en la
   repetición (fidelidad) y con lo esperado según la Tabla 20.

El grafo de cada repetición se construye en memoria con el mismo `build_graph` del exportador,
a partir de los resultados de las compuertas (sin pasar por MLflow), para no ralentizar la
campaña; la fidelidad del paso por MLflow se verifica aparte, con `lineage_fidelity`.
"""
from __future__ import annotations

import json
import time
import uuid

from rdflib import RDF, XSD, Graph, Literal

from fairgate.semantic.export import DQV, FAIR, PROV, PipelineRun, build_graph, validate
from fairgate.semantic.queries import run_query

from .configs import intensity_of
from .protocol import Protocol


def _gate_entry(result, registered_as=None, reasons=None) -> dict:
    return {"run_id": uuid.uuid4().hex, "result": json.loads(result.to_json()),
            "model_registered_as": registered_as, "reasons": reasons or []}


def pipeline_run(rep) -> PipelineRun:
    """La repetición con la misma estructura que el exportador lee de MLflow."""
    dataset = rep.prepared.domain.dataset.name
    c3 = rep.results["C3"]
    gates = [_gate_entry(r) for g in ("C1", "C2") for r in rep.results[g]]
    c3_entries = [_gate_entry(r, f"{dataset}-scoring" if r.passed and i == len(c3) - 1 else None)
                  for i, r in enumerate(c3)]
    gates += c3_entries
    reasons = [[] if df is None else json.loads(df.to_json(orient="records")) for df in rep.reasons]
    ops = [{
        "run_id": uuid.uuid4().hex,
        "model_run_id": c3_entries[-1]["run_id"],
        "gates": [_gate_entry(r, reasons=rs) for r, rs in zip(rep.results["C4"], reasons)],
    }]
    return PipelineRun(uuid.uuid4().hex, dataset, rep.prepared.batch_hash, len(rep.prepared.batch), gates, ops)


def _failed_block(results) -> set[tuple]:
    return {(r.contract_id, f.rule_id, f.attribute) for r in results for f in r.blocking_failures}


def pc_checks(proto: Protocol, rep, g: Graph) -> dict:
    """Fidelidad de las cinco preguntas de competencia frente a lo ocurrido en la repetición."""
    all_results = [r for rs in rep.results.values() for r in rs]
    c3, c4 = rep.results["C3"], rep.results["C4"]
    # SPARQL omite las variables opcionales sin valor (p. ej., el atributo de C1-SCHEMA)
    pc1 = {(r["contractId"], r["ruleId"], r.get("attribute")) for r in run_query(g, "PC1")}
    pc3 = {r["applicant"] for r in run_query(g, "PC3")}
    pc4 = run_query(g, "PC4")
    alerts = sum(int(r.extra["data_drift_alert"]) + int(r.extra["bias_drift_alert"]) for r in c4)
    explained = {pid for df in rep.reasons if df is not None for pid in df["pseudo_id"]}
    checks = {
        "PC1": pc1 == _failed_block(all_results),
        "PC2": bool(run_query(g, "PC2")) == c3[-1].passed,
        "PC3": pc3 == explained,
        "PC4": len(pc4) == alerts,
        "PC5": bool(run_query(g, "PC5")) == (len(c3) > 1),
    }
    exp = proto.expected(rep.record["scenario"], intensity_of(rep.record))
    expected = None
    if exp.gate is not None:  # Tabla 20: la PC1 debe devolver la regla esperada
        expected = any(rule in exp.rules for _, rule, _ in pc1)
        if rep.record["scenario"] == "E4":  # y la PC5, la comparación base frente a remediado
            expected = expected and checks["PC5"] and len(c3) > 1
    return {"fidelity": checks, "expected": expected}


def audit_repetition(proto: Protocol, rep) -> dict:
    t0 = time.perf_counter()
    g = build_graph(pipeline_run(rep))
    conforms, _ = validate(g)
    out = {"conforms": conforms, "triples": len(g), **pc_checks(proto, rep, g)}
    out["seconds"] = round(time.perf_counter() - t0, 3)
    return out


# --------------------------------------------------------------------------- pruebas negativas


def _first(g: Graph, rdf_type):
    return next(iter(sorted(g.subjects(RDF.type, rdf_type))), None)


def negative_cases(g: Graph) -> dict[str, Graph]:
    """Copias del grafo con una alteración cada una; todas deben ser rechazadas por SHACL."""
    cases: dict[str, Graph] = {}

    def altered(name, fn):
        h = Graph()
        for t in g:
            h.add(t)
        if fn(h) is not False:
            cases[name] = h

    def no_contract(h):  # ejecución sin contrato: no aplica ninguna regla
        e = _first(h, FAIR.GateExecution)
        h.remove((e, FAIR.appliesRule, None))

    def rule_without_contract(h):
        r = _first(h, FAIR.Rule)
        h.remove((r, FAIR.partOfContract, None))

    def measurement_without_rule(h):
        m = _first(h, FAIR.FairnessMeasurement)
        h.remove((m, FAIR.measuresRule, None))

    def measurement_without_value(h):
        m = _first(h, FAIR.FairnessMeasurement)
        h.remove((m, DQV.value, None))

    def model_without_batch(h):
        m = _first(h, FAIR.ModelVersion)
        if m is None:
            return False
        h.remove((m, PROV.wasDerivedFrom, None))

    def wrong_datatype(h):  # el valor de una medición como texto
        m = _first(h, FAIR.FairnessMeasurement)
        v = h.value(m, DQV.value)
        h.remove((m, DQV.value, None))
        h.add((m, DQV.value, Literal(str(v), datatype=XSD.string)))

    def batch_without_hash(h):
        b = _first(h, FAIR.DataBatch)
        h.remove((b, FAIR.dvcHash, None))

    def reason_without_model(h):
        r = _first(h, FAIR.AdverseActionReason)
        if r is None:
            return False
        h.remove((r, FAIR.explainsDecisionOf, None))

    for name, fn in [("ejecucion_sin_contrato", no_contract), ("regla_sin_contrato", rule_without_contract),
                     ("medicion_sin_regla", measurement_without_rule),
                     ("medicion_sin_valor", measurement_without_value),
                     ("modelo_sin_lote", model_without_batch), ("tipo_de_dato_incorrecto", wrong_datatype),
                     ("lote_sin_hash", batch_without_hash), ("razon_sin_modelo", reason_without_model)]:
        altered(name, fn)
    return cases


def negative_tests(g: Graph) -> dict[str, bool]:
    """Para cada alteración, si el validador la rechazó (True es el resultado esperado)."""
    return {name: not validate(h)[0] for name, h in negative_cases(g).items()}


# --------------------------------------------------------------------------- linaje frente a MLflow


def log_repetition(rep, tracking_uri: str) -> str:
    """Registra la repetición en MLflow como lo hace el pipeline; devuelve la ejecución padre."""
    from fairgate.lineage import Lineage

    prep = rep.prepared
    dataset = prep.domain.dataset.name
    lin = Lineage(dataset, prep.batch_hash, len(prep.batch), tracking_uri=tracking_uri)
    pipeline_id = lin.run_id
    model_run = None
    for g in ("C1", "C2", "C3"):
        for r in rep.results[g]:
            model_run = lin.log_gate(r)
    lin.close(all(r.passed for g in ("C1", "C2", "C3") for r in rep.results[g]))
    op = Lineage(dataset, prep.batch_hash, len(prep.batch), tracking_uri=tracking_uri, role="operacion",
                 tags={"fairgate.pipeline_run_id": pipeline_id, "fairgate.model_run_id": model_run})
    for r, df in zip(rep.results["C4"], rep.reasons):
        arts = None if df is None else {"rejection_reasons.json": df.to_json(orient="records", force_ascii=False)}
        op.log_gate(r, artifacts=arts)
    op.close(all(r.passed for r in rep.results["C4"]))
    return pipeline_id


def lineage_fidelity(dataset: str, pipeline_run_id: str, tracking_uri: str) -> dict:
    """Compara el grafo exportado con MLflow: ejecuciones, contratos, lotes y valores medidos."""
    from mlflow import MlflowClient

    from fairgate.lineage import experiment_name
    from fairgate.semantic.export import load_pipeline_run

    g = build_graph(load_pipeline_run(dataset, pipeline_run_id, tracking_uri))
    client = MlflowClient(tracking_uri=tracking_uri)
    exp = client.get_experiment_by_name(experiment_name(dataset))
    parents = [pipeline_run_id] + [
        r.info.run_id for r in client.search_runs(
            [exp.experiment_id], f"tags.`fairgate.pipeline_run_id` = '{pipeline_run_id}'")
    ]
    children = [c for p in parents for c in client.search_runs(
        [exp.experiment_id], f"tags.`mlflow.parentRunId` = '{p}'")]

    executions = {str(g.value(e, FAIR.mlflowRunId)): e for e in g.subjects(RDF.type, FAIR.GateExecution)}
    issues: list[str] = []
    values_checked = 0
    for run in children:
        rid, params, metrics = run.info.run_id, run.data.params, run.data.metrics
        e = executions.get(rid)
        if e is None:
            issues.append(f"{rid}: ejecución ausente del grafo")
            continue
        versions = {str(g.value(c, FAIR.version)) for r in g.objects(e, FAIR.appliesRule)
                    for c in g.objects(r, FAIR.partOfContract)}
        if versions != {params["contract_version"]}:
            issues.append(f"{rid}: versión del contrato {versions} ≠ {params['contract_version']}")
        used = list(g.objects(e, PROV.used))
        hashes = {str(g.value(u, FAIR.dvcHash)) for u in used if g.value(u, FAIR.dvcHash) is not None}
        hashes |= {str(g.value(b, FAIR.dvcHash)) for u in used for b in g.objects(u, PROV.wasDerivedFrom)
                   if g.value(b, FAIR.dvcHash) is not None}
        if params["batch_hash"] not in hashes:
            issues.append(f"{rid}: lote {params['batch_hash']} ausente del grafo")
        graph_values = {}
        for m in g.subjects(PROV.wasGeneratedBy, e):
            if (m, RDF.type, FAIR.FairnessMeasurement) not in g:
                continue
            rule = str(g.value(g.value(m, FAIR.measuresRule), FAIR.ruleId))
            attr = g.value(m, FAIR.concernsAttribute)
            key = rule + (f".{g.value(attr, FAIR.attributeName)}" if attr is not None else "")
            graph_values[key] = float(g.value(m, DQV.value))
        for name, value in metrics.items():
            if not name.endswith(".value"):
                continue
            key = name[: -len(".value")]
            values_checked += 1
            if key not in graph_values:
                issues.append(f"{rid}: medición {key} ausente del grafo")
            elif abs(graph_values[key] - value) > 1e-6:
                issues.append(f"{rid}: {key} = {graph_values[key]} en el grafo y {value} en MLflow")
    return {
        "executions_mlflow": len(children),
        "executions_graph": len(executions),
        "values_checked": values_checked,
        "issues": issues,
        "ok": not issues and len(children) == len(executions),
    }
