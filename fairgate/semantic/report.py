"""Generador del reporte de cumplimiento (Zona 4). Todo su contenido sale de consultas SPARQL
sobre el grafo validado; el reporte también se registra en el grafo (fair:ComplianceReport)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from rdflib import RDF, XSD, Graph, Literal, Namespace

from .export import FAIR, PROV, PipelineRun, _slug
from .queries import QUERIES, run_query


def _fmt(v, nd=4):
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "Sí" if v else "No"
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def add_report_node(g: Graph, run: PipelineRun) -> None:
    ex = Namespace(f"https://pucp.edu.pe/fairgate/{_slug(run.dataset)}/")
    node = ex[f"report/{run.run_id}"]
    g.add((node, RDF.type, FAIR.ComplianceReport))
    g.add((node, PROV.generatedAtTime, Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime)))
    for exec_node in g.subjects(RDF.type, FAIR.GateExecution):
        g.add((node, FAIR.documents, exec_node))


def write_pdf(g: Graph, run: PipelineRun, conforms: bool, path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=8, leading=10)
    story = []

    def h(text, level=1):
        story.append(Paragraph(text, styles["Heading1" if level == 1 else "Heading2"]))

    def p(text):
        story.append(Paragraph(text, styles["BodyText"]))

    def table(header, rows, widths=None):
        data = [[Paragraph(f"<b>{c}</b>", small) for c in header]]
        data += [[Paragraph(str(c), small) for c in r] for r in rows]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.3 * cm))

    meds = run_query(g, "MEDICIONES")
    gates = {}
    for m in meds:
        gates.setdefault((m["contractId"], m["subject"]), m)
    # El pipeline son las compuertas del desarrollo; el C4 se evalúa después, en la operación.
    pipeline_ok = all(m["gatePassed"] for (cid, _), m in gates.items() if cid != "C4")
    op_batches = sorted({subject for (cid, subject) in gates if cid == "C4"})

    h(f"Reporte de cumplimiento de equidad — {run.dataset}")
    p(f"Ejecución del pipeline (MLflow): <b>{run.run_id}</b><br/>"
      f"Lote evaluado: hash DVC <b>{run.batch_hash}</b>, {run.records_count} registros<br/>"
      f"Resultado del pipeline (C1 a C3): <b>{'APROBADO' if pipeline_ok else 'DETENIDO'}</b><br/>"
      f"Lotes de producción evaluados por el C4: <b>{len(op_batches)}</b><br/>"
      f"Conformidad del grafo con las formas SHACL: <b>{'conforma' if conforms else 'NO conforma'}</b><br/>"
      f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    h("1. Resultado de cada compuerta", 2)
    table(
        ["Contrato", "Evaluado", "Regla", "Severidad", "Atributo", "Valor", "IC 95 %", "Decisión", "Umbral", "Cumple"],
        [[f"{m['contractId']} v{m['version']}", m["subject"], m["ruleId"], m["severity"], m.get("attribute") or "—",
          _fmt(m["value"]),
          f"[{_fmt(m.get('ciLow'))}; {_fmt(m.get('ciHigh'))}]" if m.get("ciLow") is not None else "—",
          _fmt(m["decision"]), f"{m['operator']} {_fmt(m['threshold'], 2)}", _fmt(m["passed"])] for m in meds],
    )

    h("2. Reglas que bloquearon (PC1)", 2)
    pc1 = run_query(g, "PC1")
    if pc1:
        table(["Contrato", "Regla", "Atributo", "Valor", "Decisión", "Umbral", "Evaluado", "Paso"],
              [[r["contractId"], r["ruleId"], r.get("attribute") or "—", _fmt(r["value"]), _fmt(r["decision"]),
                f"{r['operator']} {_fmt(r['threshold'], 2)}", r["subject"], r.get("step") or "—"] for r in pc1])
    else:
        p("Ninguna regla de severidad <i>block</i> se incumplió.")

    h("3. Modelo aprobado y lote de entrenamiento (PC2)", 2)
    pc2 = run_query(g, "PC2")
    if pc2:
        table(["Registrado como", "Versión", "Ejecución MLflow", "Exactitud balanceada", "Hash del lote", "Registros"],
              [[r["registeredAs"], r["stage"], r["runId"], _fmt(r.get("balancedAccuracy")), r["hash"], r["records"]]
               for r in pc2])
    else:
        p("Ningún modelo fue aprobado en esta ejecución.")

    h("4. Remediación: modelo base frente a remediado (PC5)", 2)
    pc5 = run_query(g, "PC5")
    if pc5:
        p(f"Técnica: <b>{pc5[0]['method']}</b>. Exactitud balanceada: base {_fmt(pc5[0].get('baseAcc'))}, "
          f"remediado {_fmt(pc5[0].get('remAcc'))}.")
        table(["Regla", "Atributo", "Base", "¿Cumple?", "Remediado", "¿Cumple?"],
              [[r["ruleId"], r.get("attribute") or "—", _fmt(r["baseValue"]), _fmt(r["basePassed"]),
                _fmt(r["remValue"]), _fmt(r["remPassed"])] for r in pc5])
    else:
        p("No se aplicó remediación: el modelo base cumplió el contrato o el contrato no la declara.")

    h("5. Operación: alertas de deriva del Contrato C4 (PC4)", 2)
    pc4 = run_query(g, "PC4")
    if pc4:
        table(["Tipo", "Lote", "Registros", "Reglas incumplidas", "Reentrenamiento (CT)", "Fecha"],
              [[r["alertType"], r["subject"], r["records"], r.get("rules") or "—",
                _fmt(r.get("trigger")) if r["alertType"] == "sesgo" else "—", str(r["time"])[:19]] for r in pc4])
    elif op_batches:
        p(f"Ninguno de los {len(op_batches)} lotes de producción generó alertas de deriva.")
    else:
        p("Aún no se ha evaluado ningún lote de producción con el C4.")

    h("6. Razones de rechazo (PC3)", 2)
    pc3 = run_query(g, "PC3")
    p(f"Razones de rechazo registradas: {len(pc3)}. Se generan en la operación (Zona 3).")

    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      title=f"Reporte de cumplimiento — {run.dataset}").build(story)
    return path


__all__ = ["add_report_node", "write_pdf", "QUERIES"]
