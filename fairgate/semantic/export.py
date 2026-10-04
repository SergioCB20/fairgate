"""Exportador de linaje (Zona 4): lee las ejecuciones de MLflow y las serializa como
tripletas RDF conforme a la Ontología de Fairness (PROV-O + DQV). Incluye la ejecución del
pipeline (C1 a C3) y las ejecuciones de operación del modelo que aprobó (C4, Zona 3).

MLflow es la única fuente de entrada: el exportador no accede al dataset ni al motor.
"""
from __future__ import annotations

import json
import math
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from rdflib import RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

from ..lineage import experiment_name, tracking_uri_default

FAIR = Namespace("https://pucp.edu.pe/ontology/fair#")
PROV = Namespace("http://www.w3.org/ns/prov#")
DQV = Namespace("http://www.w3.org/ns/dqv#")

HERE = Path(__file__).resolve().parent
ONTOLOGY = HERE / "ontology.ttl"
SHAPES = HERE / "shapes.ttl"


class LineageNotFound(Exception):
    pass


def _dec(v: float) -> Literal:
    return Literal(Decimal(str(round(float(v), 6))), datatype=XSD.decimal)


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(s))


@dataclass
class PipelineRun:
    run_id: str
    dataset: str
    batch_hash: str
    records_count: int
    gates: list[dict]  # [{"run_id", "result": dict, "model_registered_as": str|None}]
    # Zona 3: ejecuciones de operación del modelo aprobado (Contrato C4), cada una con sus lotes:
    # [{"run_id", "model_run_id", "gates": [...]}]
    operations: list[dict] = field(default_factory=list)


def _gate_runs(client, experiment_id: str, parent_id: str) -> list[dict]:
    children = client.search_runs(
        [experiment_id], f"tags.`mlflow.parentRunId` = '{parent_id}'", order_by=["attributes.start_time ASC"],
    )
    gates = []
    for child in children:
        with tempfile.TemporaryDirectory() as d:
            path = client.download_artifacts(child.info.run_id, "gate_result.json", d)
            result = json.loads(Path(path).read_text(encoding="utf-8"))
        versions = client.search_model_versions(f"run_id = '{child.info.run_id}'")
        gates.append({
            "run_id": child.info.run_id,
            "result": result,
            "model_registered_as": versions[0].name if versions else None,
        })
    return gates


def load_pipeline_run(dataset: str, run_id: str | None = None, tracking_uri: str | None = None) -> PipelineRun:
    """Lee de MLflow una ejecución del pipeline (la más reciente, si no se indica) y sus compuertas."""
    import os

    os.environ.setdefault("MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR", "false")
    import mlflow
    from mlflow import MlflowClient

    mlflow.set_tracking_uri(tracking_uri or tracking_uri_default())
    client = MlflowClient()
    exp = client.get_experiment_by_name(experiment_name(dataset))
    if exp is None:
        raise LineageNotFound(f"No hay linaje en MLflow para '{dataset}'. Ejecute primero el pipeline.")
    if run_id is None:
        parents = client.search_runs(
            [exp.experiment_id], "tags.`fairgate.role` = 'pipeline'", order_by=["attributes.start_time DESC"],
            max_results=1,
        )
        if not parents:
            raise LineageNotFound(f"No hay ejecuciones del pipeline para '{dataset}'.")
        parent = parents[0]
    else:
        parent = client.get_run(run_id)

    gates = _gate_runs(client, exp.experiment_id, parent.info.run_id)
    ops = client.search_runs(
        [exp.experiment_id],
        f"tags.`fairgate.role` = 'operacion' and tags.`fairgate.pipeline_run_id` = '{parent.info.run_id}'",
        order_by=["attributes.start_time ASC"],
    )
    operations = [
        {
            "run_id": op.info.run_id,
            "model_run_id": op.data.tags["fairgate.model_run_id"],
            "gates": _gate_runs(client, exp.experiment_id, op.info.run_id),
        }
        for op in ops
    ]
    tags = parent.data.tags
    return PipelineRun(
        run_id=parent.info.run_id,
        dataset=dataset,
        batch_hash=tags["fairgate.batch_hash"],
        records_count=int(tags.get("fairgate.records_count", "0")),
        gates=gates,
        operations=operations,
    )


def build_graph(run: PipelineRun) -> Graph:
    g = Graph()
    g.bind("fair", FAIR)
    g.bind("prov", PROV)
    g.bind("dqv", DQV)
    ex = Namespace(f"https://pucp.edu.pe/fairgate/{_slug(run.dataset)}/")
    g.bind("ex", ex)

    def add_batch(hash_: str, records: int) -> URIRef:
        node = ex[f"batch/{hash_}"]
        g.add((node, RDF.type, FAIR.DataBatch))
        g.add((node, FAIR.dvcHash, Literal(hash_)))
        g.add((node, FAIR.recordsCount, Literal(int(records), datatype=XSD.integer)))
        return node

    def add_execution(res: dict, run_id: str, subject_node: URIRef) -> URIRef:
        """Ejecución de compuerta con su contrato, sus reglas y una medición por regla aplicable."""
        contract = ex[f"contract/{_slug(res['contract_id'])}/v{_slug(res['contract_version'])}"]
        g.add((contract, RDF.type, FAIR.FairnessContract))
        g.add((contract, FAIR.contractId, Literal(res["contract_id"])))
        g.add((contract, FAIR.version, Literal(str(res["contract_version"]))))

        execution = ex[f"execution/{run_id}"]
        g.add((execution, RDF.type, FAIR.GateExecution))
        g.add((execution, FAIR.mlflowRunId, Literal(run_id)))
        g.add((execution, FAIR.subject, Literal(res["subject"])))
        g.add((execution, FAIR.gatePassed, Literal(bool(res["passed"]))))
        g.add((execution, PROV.startedAtTime, Literal(res["started_at"], datatype=XSD.dateTime)))
        g.add((execution, PROV.used, subject_node))

        steps: dict[str, URIRef] = {}
        for r in res["rules"]:
            rule = URIRef(contract + f"/rule/{_slug(r['rule_id'])}")
            g.add((rule, RDF.type, FAIR.Rule))
            g.add((rule, FAIR.ruleId, Literal(r["rule_id"])))
            g.add((rule, FAIR.metricName, Literal(r["metric"])))
            g.add((rule, FAIR.operator, Literal(r["operator"])))
            g.add((rule, FAIR.threshold, _dec(r["threshold"])))
            g.add((rule, FAIR.severity, Literal(r["severity"])))
            g.add((rule, FAIR.partOfContract, contract))
            g.add((execution, FAIR.appliesRule, rule))
            if not r["applicable"]:
                continue

            key = _slug(r["rule_id"] + (f"_{r['attribute']}" if r["attribute"] else ""))
            m = ex[f"measurement/{run_id}/{key}"]
            metric = ex[f"metric/{_slug(r['metric'])}"]
            g.add((metric, RDF.type, DQV.Metric))
            g.add((m, RDF.type, FAIR.FairnessMeasurement))
            g.add((m, RDF.type, DQV.QualityMeasurement))
            g.add((m, PROV.wasGeneratedBy, execution))
            g.add((m, FAIR.measuresRule, rule))
            g.add((m, DQV.isMeasurementOf, metric))
            g.add((m, DQV.computedOn, subject_node))
            g.add((m, DQV.value, _dec(r["value"])))
            g.add((m, FAIR.decisionValue, _dec(r["decision_value"])))
            g.add((m, FAIR.rulePassed, Literal(bool(r["passed"]))))
            if _ok(r.get("ci_low")) and _ok(r.get("ci_high")):
                g.add((m, FAIR.ciLow, _dec(r["ci_low"])))
                g.add((m, FAIR.ciHigh, _dec(r["ci_high"])))
            if r["attribute"]:
                attr = ex[f"attribute/{_slug(r['attribute'])}"]
                g.add((attr, RDF.type, FAIR.ProtectedAttribute))
                g.add((attr, FAIR.attributeName, Literal(r["attribute"])))
                g.add((m, FAIR.concernsAttribute, attr))
            # C2: pasos de preprocesamiento evaluados y paso donde se observó el valor
            for st in r.get("details", {}).get("by_step", []):
                node = steps.setdefault(st["step"], ex[f"execution/{run_id}/step/{_slug(st['step'])}"])
                g.add((node, RDF.type, FAIR.TransformationStep))
                g.add((node, RDFS.label, Literal(st["step"])))
                g.add((execution, FAIR.afterStep, node))
            step = r.get("details", {}).get("step")
            if step and step in steps:
                g.add((m, FAIR.atStep, steps[step]))
        return execution

    batch = add_batch(run.batch_hash, run.records_count)
    models: dict[str, URIRef] = {}  # subject -> nodo del modelo
    executions: dict[str, URIRef] = {}  # subject -> nodo de la ejecución
    for gate in run.gates:
        res, run_id = gate["result"], gate["run_id"]
        # Qué evaluó la compuerta: el lote (C1, C2) o un modelo (C3)
        subject_node = batch
        if res["subject"].startswith("modelo:"):
            stage = res["subject"].split(":", 1)[1]
            model = ex[f"model/{run_id}"]
            models[res["subject"]] = model
            g.add((model, RDF.type, FAIR.ModelVersion))
            g.add((model, FAIR.mlflowRunId, Literal(run_id)))
            g.add((model, FAIR.modelStage, Literal(stage)))
            g.add((model, PROV.wasDerivedFrom, batch))
            acc = res.get("extra", {}).get("balanced_accuracy")
            if _ok(acc):
                g.add((model, FAIR.balancedAccuracy, _dec(acc)))
            if gate["model_registered_as"]:
                g.add((model, FAIR.registeredAs, Literal(gate["model_registered_as"])))
            subject_node = model
        executions[res["subject"]] = add_execution(res, run_id, subject_node)

    # Remediación: la ejecución del modelo remediado declara la técnica en su resultado
    for gate in run.gates:
        res = gate["result"]
        rem_name = res.get("extra", {}).get("remediation")
        if res["subject"] == "modelo:remediado" and rem_name:
            rem = ex[f"remediation/{gate['run_id']}"]
            base_model, rem_model = models.get("modelo:base"), models["modelo:remediado"]
            g.add((rem, RDF.type, FAIR.Remediation))
            g.add((rem, FAIR.method, Literal(rem_name)))
            g.add((rem, PROV.used, batch))
            g.add((rem, PROV.generated, rem_model))
            if "modelo:base" in executions:
                g.add((rem, PROV.wasInformedBy, executions["modelo:base"]))
            if base_model is not None:
                g.add((rem_model, PROV.wasDerivedFrom, base_model))

    # Zona 3: cada lote de producción evaluado por el C4 y las alertas de deriva que generó
    for op in run.operations:
        model = ex[f"model/{op['model_run_id']}"]
        for gate in op["gates"]:
            res, run_id = gate["result"], gate["run_id"]
            extra = res.get("extra", {})
            prod_batch = add_batch(res["batch_hash"], extra.get("records_count", 0))
            execution = add_execution(res, run_id, prod_batch)
            g.add((execution, PROV.used, model))  # modelo que puntuó el lote
            for kind, flag in (("datos", "data_drift_alert"), ("sesgo", "bias_drift_alert")):
                if not extra.get(flag):
                    continue
                alert = ex[f"alert/{run_id}/{kind}"]
                g.add((alert, RDF.type, FAIR.DriftAlert))
                g.add((alert, FAIR.alertType, Literal(kind)))
                g.add((alert, FAIR.raisedOn, prod_batch))
                g.add((alert, PROV.wasGeneratedBy, execution))
                g.add((alert, PROV.generatedAtTime, Literal(res["started_at"], datatype=XSD.dateTime)))
                if kind == "sesgo":
                    g.add((alert, FAIR.triggersRetraining, Literal(bool(extra.get("trigger_ct")))))
    return g


def validate(g: Graph) -> tuple[bool, str]:
    """Valida el grafo contra las formas SHACL, con inferencia RDFS sobre la ontología."""
    from pyshacl import validate as shacl_validate

    shapes = Graph().parse(SHAPES)
    ontology = Graph().parse(ONTOLOGY)
    conforms, _, text = shacl_validate(g, shacl_graph=shapes, ont_graph=ontology, inference="rdfs")
    return bool(conforms), text


def export(dataset: str, out_dir: Path, run_id: str | None = None, tracking_uri: str | None = None):
    """MLflow → RDF → SHACL. Solo escribe el grafo si conforma las formas."""
    run = load_pipeline_run(dataset, run_id, tracking_uri)
    g = build_graph(run)
    conforms, report = validate(g)
    path = None
    if conforms:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{run.dataset}-{run.batch_hash[:8]}-{run.run_id[:8]}.ttl"
        g.serialize(path, format="turtle")
    return run, g, conforms, report, path
