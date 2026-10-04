"""Línea de comandos.

    python -m fairgate validate domains/davronov   # valida dataset.yaml y contratos (sin datos)
    python -m fairgate run domains/davronov        # ejecuta C1 → C2 → C3; exit 1 si bloquea
    python -m fairgate monitor domains/davronov    # Zona 3: C4 sobre lotes de producción; exit 1 = Trigger CT
    python -m fairgate export domains/davronov     # MLflow → RDF → SHACL (Zona 4)
    python -m fairgate query domains/davronov PC1  # pregunta de competencia sobre el grafo
    python -m fairgate report domains/davronov     # grafo + reporte de cumplimiento en PDF
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .data import PROJECT_ROOT, load_domain
from .engine import DataNotAvailable, Session
from .gates import check_contract, expected_cases


def _print_result(res) -> None:
    status = "APRUEBA" if res.passed else "BLOQUEA"
    print(f"\n== {res.contract_id} v{res.contract_version} · {res.subject} · {status}")
    for r in res.rules:
        if not r.applicable:
            print(f"   {r.key}: no aplica ({r.details.get('reason', '')})")
            continue
        mark = "ok " if r.passed else ("WARN" if r.severity == "warn" else "FALLA")
        print(f"   [{mark}] {r.message()}")
        if not r.passed and "step" in r.details:
            print(f"          paso responsable: {r.details['step']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fairgate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "run", "monitor", "export", "query", "report"):
        p = sub.add_parser(name)
        p.add_argument("domain")
        if name in ("run", "monitor"):
            p.add_argument("--no-lineage", action="store_true", help="no registrar en MLflow")
        if name == "monitor":
            p.add_argument("batches", nargs="*", help="CSV de lotes de producción; sin ellos, operación simulada")
            p.add_argument("--simulate", type=int, default=None,
                           help="número de lotes simulados a partir del conjunto de prueba (por defecto, el del C4)")
        if name == "query":
            p.add_argument("question", help="PC1..PC5 o MEDICIONES")
        if name in ("export", "query", "report"):
            p.add_argument("--run-id", default=None, help="ejecución del pipeline en MLflow (por defecto, la última)")
    args = parser.parse_args(argv)

    domain = load_domain(args.domain)
    if args.cmd in ("export", "query", "report"):
        return _semantic(args, domain.dataset.name)
    if args.cmd == "monitor":
        return _monitor(args, domain)
    if args.cmd == "validate":
        for c in domain.contracts_in_order():
            check_contract(c, domain.dataset)
            print(f"{c.contract_id} v{c.version} ({c.gate}): {len(expected_cases(c))} pruebas")
        print("Contratos válidos.")
        return 0

    try:
        session = Session(domain, log_lineage=False if args.no_lineage else None)
        outcomes = session.run()
    except DataNotAvailable as e:
        print(e, file=sys.stderr)
        return 2
    for out in outcomes:
        for res in out.results:
            _print_result(res)
    blocked = next((o for o in outcomes if not o.passed), None)
    if blocked:
        print(f"\nPipeline DETENIDO por {blocked.gate}.")
        return 1
    print("\nPipeline aprobado.")
    return 0


def _monitor(args, domain) -> int:
    """Zona 3. Con linaje, el modelo se carga del registro de MLflow (Trigger CD); sin linaje, se
    ejecuta el pipeline en memoria y se despliega el modelo que apruebe el C3."""
    from .monitoring import Monitor, MonitorError, read_batch, simulate_batches

    try:
        if args.no_lineage:
            session = Session(domain, log_lineage=False)
            blocked = next((o for o in session.run() if not o.passed), None)
            if blocked:
                print(f"Pipeline DETENIDO por {blocked.gate}: no hay modelo que desplegar.", file=sys.stderr)
                return 1
            monitor = Monitor.from_session(session, log_lineage=False)
        else:
            monitor = Monitor.from_registry(domain)
        if args.batches:
            batches = [read_batch(b, domain) for b in args.batches]
        else:
            from .data import load_batch, split

            k = args.simulate or int(monitor.contract.params.get("batches", 4))
            _, test = split(domain, load_batch(domain)[0])
            batches = simulate_batches(test, k, random_state=domain.dataset.split.random_state)
            print(f"Operación simulada: {k} lotes a partir del conjunto de prueba ({len(test)} registros).")
        outcomes = monitor.run(batches)
    except (MonitorError, DataNotAvailable) as e:
        print(e, file=sys.stderr)
        return 2
    for out in outcomes:
        _print_result(out.result)
        extra = out.result.extra
        if extra["data_drift_alert"]:
            drifted = out.result.find(next(r.rule_id for r in out.result.rules if r.metric == "drift_share"), None)
            print(f"   ALERTA de deriva de datos (warn): {', '.join(drifted.details['drifted'])}")
        if extra["bias_drift_alert"]:
            print("   ALERTA de deriva del sesgo: Trigger CT (reentrenamiento hacia la Zona 1)")
    n_alerts = sum(o.result.extra["bias_drift_alert"] for o in outcomes)
    print(f"\n{len(outcomes)} lotes evaluados · {n_alerts} con deriva del sesgo.")
    if monitor.trigger_ct:
        print("Trigger CT: reentrenar el modelo.")
        return 1
    return 0


def _semantic(args, dataset: str) -> int:
    from .semantic.export import LineageNotFound, export, validate
    from .semantic.queries import QUERIES, run_query
    from .semantic.report import add_report_node, write_pdf

    try:
        run, graph, conforms, shacl_text, path = export(dataset, PROJECT_ROOT / "lineage", args.run_id)
    except LineageNotFound as e:
        print(e, file=sys.stderr)
        return 2
    print(f"Pipeline {run.run_id} · lote {run.batch_hash} · {len(run.gates)} ejecuciones de compuerta · "
          f"{len(graph)} tripletas")
    if not conforms:
        print("El grafo NO conforma las formas SHACL; no se incorpora al repositorio.\n" + shacl_text)
        return 1
    print(f"SHACL: conforma. Grafo: {path}")

    if args.cmd == "query":
        name = args.question.upper()
        if name not in QUERIES:
            print(f"Pregunta desconocida. Disponibles: {', '.join(QUERIES)}", file=sys.stderr)
            return 2
        print(f"\n{name}: {QUERIES[name][0]}")
        rows = run_query(graph, name)
        for row in rows:
            print("  " + " | ".join(f"{k}={v}" for k, v in row.items()))
        print(f"({len(rows)} resultados)")
    elif args.cmd == "report":
        add_report_node(graph, run)
        conforms, shacl_text = validate(graph)
        if not conforms:
            print("El grafo con el reporte NO conforma las formas SHACL.\n" + shacl_text)
            return 1
        graph.serialize(path, format="turtle")
        pdf = write_pdf(graph, run, conforms, PROJECT_ROOT / "reports" / (Path(path).stem + ".pdf"))
        print(f"Reporte de cumplimiento: {pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
