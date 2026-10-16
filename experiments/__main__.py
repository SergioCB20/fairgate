"""Línea de comandos de la evaluación experimental (O4).

    python -m experiments ejecutar --semillas humo                 # verifica la infraestructura
    python -m experiments ejecutar --semillas calibracion --escenarios E0,E5
    python -m experiments congelar --nota "..."                    # congela los contratos (6.2.5)
    python -m experiments ejecutar --semillas evaluacion --auditoria  # solo con contratos congelados
    python -m experiments analizar experiments/resultados/evaluacion-logistic_regression.jsonl
    python -m experiments auditar-linaje --semilla 9000            # 6.4: negativas y linaje vs MLflow
    python -m experiments exportar-deriva --semillas calibracion   # lotes para comparar con Evidently
    python -m experiments preparar-hmda                            # E6: descarga y prepara HMDA
    python -m experiments congelar --dominio domains/hmda --nota "..."
    python -m experiments e6 --semillas evaluacion                 # E6: deriva real (HMDA)

Las semillas de evaluación solo se aceptan si los contratos coinciden con los congelados
(`experiments/congelamiento.json`): así la evaluación no hereda ajustes hechos a la vista de sus
resultados.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fairgate.data import PROJECT_ROOT

from .protocol import DAVRONOV, SCENARIOS, SEEDS

RESULTS = PROJECT_ROOT / "experiments" / "resultados"
FREEZE = PROJECT_ROOT / "experiments" / "congelamiento.json"


def contract_hashes(domain: str) -> dict[str, str]:
    folder = PROJECT_ROOT / domain
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(folder.glob("*.yaml"))}


def freeze_path(domain: str) -> Path:
    """Davronov conserva el archivo original; cada dominio adicional tiene el suyo."""
    name = Path(domain).name
    return FREEZE if name == "davronov" else FREEZE.with_name(f"congelamiento-{name}.json")


def frozen_ok(domain: str) -> tuple[bool, str]:
    path = freeze_path(domain)
    if not path.exists():
        return False, f"los contratos de {domain} no están congelados (python -m experiments congelar)"
    frozen = json.loads(path.read_text(encoding="utf-8"))["hashes"]
    current = contract_hashes(domain)
    changed = sorted(k for k in set(frozen) | set(current) if frozen.get(k) != current.get(k))
    return (not changed, f"cambiaron desde el congelamiento: {', '.join(changed)}" if changed else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("ejecutar", help="ejecuta repeticiones y agrega registros JSONL")
    run.add_argument("--semillas", choices=sorted(SEEDS), required=True)
    run.add_argument("--escenarios", default=",".join(SCENARIOS))
    run.add_argument("--clasificador", default=None, help="por defecto, el de dataset.yaml")
    run.add_argument("--repeticiones", type=int, default=None, help="usar solo las primeras N semillas")
    run.add_argument("--auditoria", action="store_true", help="grafo, SHACL y PC por repetición (6.4)")
    run.add_argument("--salida", default=None)

    freeze = sub.add_parser("congelar", help="registra el hash de los contratos antes de la evaluación")
    freeze.add_argument("--nota", required=True)
    freeze.add_argument("--dominio", default=None, help="por defecto, el del protocolo (Davronov)")

    sub.add_parser("preparar-hmda", help="E6: descarga HMDA (Delaware, 2022 y 2023) y escribe la referencia y los lotes")

    e6 = sub.add_parser("e6", help="E6: deriva real con HMDA (requiere preparar-hmda y, en evaluación, congelar)")
    e6.add_argument("--semillas", choices=sorted(SEEDS), required=True)
    e6.add_argument("--repeticiones", type=int, default=None)
    e6.add_argument("--clasificador", default=None)
    e6.add_argument("--salida", default=None)

    an = sub.add_parser("analizar", help="consolida un archivo JSONL en un reporte Markdown")
    an.add_argument("registros")
    an.add_argument("--salida", default=None)

    au = sub.add_parser("auditar-linaje", help="pruebas negativas y linaje frente a MLflow (6.4)")
    au.add_argument("--semilla", type=int, default=SEEDS["humo"][0])
    au.add_argument("--escenario", default="E4")
    au.add_argument("--intensidad", type=float, default=0.30)

    st = sub.add_parser("estabilidad", help="estabilidad de las razones de rechazo entre semillas (6.4)")
    st.add_argument("--semillas", choices=sorted(SEEDS), required=True)
    st.add_argument("--repeticiones", type=int, default=None)
    st.add_argument("--clasificador", default=None)

    dr = sub.add_parser("exportar-deriva", help="lotes de E0 y E5 para la comparación con Evidently (6.2.6)")
    dr.add_argument("--semillas", choices=sorted(SEEDS), default="calibracion")
    dr.add_argument("--repeticiones", type=int, default=3)
    dr.add_argument("--salida", required=True)

    args = parser.parse_args(argv)
    proto = DAVRONOV

    if args.cmd == "congelar":
        domain = args.dominio or proto.domain
        payload = {"fecha": datetime.now(timezone.utc).isoformat(), "nota": args.nota,
                   "dominio": domain, "hashes": contract_hashes(domain)}
        path = freeze_path(domain)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Contratos congelados en {path}")
        return 0

    if args.cmd == "preparar-hmda":
        from .hmda import prepare

        print(json.dumps(prepare(), ensure_ascii=False, indent=2, default=str))
        return 0

    if args.cmd == "e6":
        from . import e6

        if args.semillas == "evaluacion":
            ok, why = frozen_ok(e6.DOMAIN)
            if not ok:
                print(f"No se puede ejecutar la evaluación: {why}.", file=sys.stderr)
                return 2
        est = args.clasificador or "dataset"
        out = Path(args.salida) if args.salida else RESULTS / f"e6-{args.semillas}-{est}.jsonl"
        n = e6.campaign(SEEDS[args.semillas][: args.repeticiones], out, args.clasificador,
                        log=lambda m: print(m, flush=True))
        records = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
        out.with_suffix(".md").write_text(e6.report(records), encoding="utf-8")
        print(f"{n} registros nuevos en {out}; reporte en {out.with_suffix('.md')}")
        return 0

    if args.cmd in ("ejecutar", "estabilidad") and args.semillas == "evaluacion":
        ok, why = frozen_ok(proto.domain)
        if not ok:
            print(f"No se puede ejecutar la evaluación: {why}.", file=sys.stderr)
            return 2

    if args.cmd == "estabilidad":
        from .stability import reason_stability

        result = reason_stability(proto, SEEDS[args.semillas][: args.repeticiones], args.clasificador)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.cmd == "ejecutar":
        from .runner import campaign

        seeds =SEEDS[args.semillas][: args.repeticiones]
        scenarios = [s.strip() for s in args.escenarios.split(",") if s.strip()]
        est = args.clasificador or "dataset"
        out = Path(args.salida) if args.salida else RESULTS / f"{args.semillas}-{est}.jsonl"
        n = campaign(proto, seeds, scenarios, out, args.clasificador, args.auditoria,
                     log=lambda m: print(m, flush=True))
        print(f"{n} registros nuevos en {out}")
        return 0

    if args.cmd == "analizar":
        from .analysis import load, report

        path = Path(args.registros)
        text = report(load(path), proto, f"Resultados: {path.stem}")
        out = Path(args.salida) if args.salida else path.with_suffix(".md")
        out.write_text(text, encoding="utf-8")
        print(f"Reporte: {out}")
        return 0

    if args.cmd == "auditar-linaje":
        from fairgate.data import load_batch, load_domain
        from fairgate.semantic.export import build_graph

        from .audit import lineage_fidelity, log_repetition, negative_tests, pipeline_run
        from .runner import run_development

        base = load_domain(proto.domain)
        df, _ = load_batch(base)
        intensity = None if args.escenario == "E0" else args.intensidad
        rep = run_development(proto, base, df, args.escenario, intensity, args.semilla)
        g = build_graph(pipeline_run(rep))
        neg = negative_tests(g)
        # En Windows, MLflow mantiene abierta la base SQLite: se ignora el error al limpiar.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            uri = f"sqlite:///{(Path(d) / 'mlflow.db').as_posix()}"
            import os

            os.environ["MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR"] = "false"
            cwd = os.getcwd()
            os.chdir(d)  # los artefactos de MLflow quedan en el directorio temporal
            try:
                fid = lineage_fidelity(rep.prepared.domain.dataset.name, log_repetition(rep, uri), uri)
            finally:
                os.chdir(cwd)
        result = {"escenario": args.escenario, "intensidad": intensity, "semilla": args.semilla,
                  "negativas_rechazadas": neg, "linaje": fid}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if all(neg.values()) and fid["ok"] else 1

    if args.cmd == "exportar-deriva":
        from .drift_export import export_drift_batches

        n = export_drift_batches(proto, SEEDS[args.semillas][: args.repeticiones], Path(args.salida))
        print(f"{n} lotes exportados en {args.salida}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
