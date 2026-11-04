"""Generador del reporte de cumplimiento (Zona 4). Sus resultados salen de consultas SPARQL sobre el
grafo validado; el reporte también se registra en el grafo (fair:ComplianceReport).

Es evidencia de auditoría: identifica a los solicitantes solo por seudónimo y no incluye nombres ni
los valores de sus variables. Los nombres internos (reglas, variables) no cambian en el grafo; aquí
solo se traducen al mostrarlos. Las etiquetas propias de cada caso están en
`domains/<caso>/reporte/etiquetas.yaml`, en una subcarpeta para no alterar los hashes del
congelamiento de los contratos (`experiments/__main__.py`).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import yaml
from rdflib import RDF, XSD, Graph, Literal, Namespace

from .export import FAIR, PROV, PipelineRun, _slug
from .queries import QUERIES, run_query

SEVERITY = {"block": "Bloqueante", "warn": "Advertencia"}
OPERATOR = {"le": "≤", "ge": "≥", "lt": "<", "gt": ">", "eq": "="}
METHOD = {"reweighing": "Reponderación"}
ALERT = {"datos": "Deriva de datos", "sesgo": "Deriva del sesgo"}
SUBJECT = {"lote": "Lote de datos", "pasos": "Pasos de preprocesamiento",
           "modelo:base": "Modelo base", "modelo:remediado": "Modelo remediado"}
METRIC = {
    "schema_violations": "Violaciones del esquema",
    "max_null_ratio": "Proporción máxima de nulos",
    "duplicate_ratio": "Proporción de duplicados",
    "forbidden_features": "Columnas prohibidas entre las variables",
    "max_feature_target_auc": "Fuga de la etiqueta (AUC máximo)",
    "min_group_proportion": "Proporción mínima del grupo",
    "leakage_auc": "Filtración del atributo protegido (AUC)",
    "leakage_auc_increment": "Aumento de la filtración por paso",
    "spd": "Diferencia de Paridad Estadística (SPD)",
    "eod": "Diferencia de Igualdad de Oportunidades (EOD)",
    "di": "Impacto Dispar (DI)",
    "balanced_accuracy_drop": "Caída de la exactitud balanceada",
    "drift_share": "Proporción de variables con deriva",
}
CONTRACTS = {
    "C1": "Calidad y representación del lote",
    "C2": "Filtración del atributo protegido en el preprocesamiento",
    "C3": "Equidad del modelo entrenado",
    "C4": "Deriva de los datos y del sesgo en producción",
}
COLOR_OK, COLOR_FAIL, COLOR_WARN = "#1b6e3c", "#b3261e", "#8a5a00"
HEADER, ZEBRA, GRID = "#1f3a5f", "#f3f5f8", "#c5cbd3"


class Markup(str):
    """Texto de una celda que ya trae marcado de ReportLab y no se debe escapar."""


def _fmt(v, nd=4):
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "Sí" if v else "No"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{n:.{nd}f}".replace(".", ",").replace("-", "−")


def _int(v):
    return f"{int(v):,}".replace(",", " ")


def _threshold(operator, threshold):
    return f"{OPERATOR.get(operator, operator)} {_fmt(threshold, 2)}"


def _subject(subject):
    return SUBJECT.get(subject, subject.split(":", 1)[1] if subject.startswith("lote:") else subject)


def _stage(stage):
    return SUBJECT.get(f"modelo:{stage}", stage)


def _colored(text, color):
    return Markup(f'<font color="{color}"><b>{escape(text)}</b></font>')


def _rule_result(m):
    if m["passed"]:
        return _colored("Cumple", COLOR_OK)
    return _colored("Advertencia", COLOR_WARN) if m["severity"] == "warn" else _colored("No cumple", COLOR_FAIL)


def load_labels(domain_dir: Path | None) -> dict:
    """Etiquetas del caso. Sin archivo, las variables se muestran con su nombre interno."""
    path = Path(domain_dir) / "reporte" / "etiquetas.yaml" if domain_dir else None
    if path is None or not path.exists():
        return {"variables": {}, "notas": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {"variables": data.get("variables") or {}, "notas": data.get("notas") or []}


def latest_executions(meds: list[dict]) -> dict[tuple[str, str], object]:
    """Fecha de la última ejecución de cada compuerta sobre cada sujeto. El monitor puede volver a
    evaluar los mismos lotes de un pipeline; el grafo conserva todas las ejecuciones."""
    latest: dict[tuple[str, str], object] = {}
    for m in meds:
        key = (m["contractId"], m["subject"])
        if key not in latest or m["timestamp"] > latest[key]:
            latest[key] = m["timestamp"]
    return latest


def add_report_node(g: Graph, run: PipelineRun) -> None:
    ex = Namespace(f"https://pucp.edu.pe/fairgate/{_slug(run.dataset)}/")
    node = ex[f"report/{run.run_id}"]
    g.add((node, RDF.type, FAIR.ComplianceReport))
    g.add((node, PROV.generatedAtTime, Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime)))
    for exec_node in g.subjects(RDF.type, FAIR.GateExecution):
        g.add((node, FAIR.documents, exec_node))


def _register_fonts() -> tuple[str, str, str]:
    """Vera viene con ReportLab e incluye ≤, ≥ y −, que Helvetica no puede mostrar."""
    import reportlab
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    folder = Path(reportlab.__file__).parent / "fonts"
    for name, file in (("Vera", "Vera.ttf"), ("Vera-Bold", "VeraBd.ttf"),
                       ("Vera-Italic", "VeraIt.ttf"), ("Vera-BoldItalic", "VeraBI.ttf")):
        pdfmetrics.registerFont(TTFont(name, os.fspath(folder / file)))
    addMapping("Vera", 0, 0, "Vera")
    addMapping("Vera", 1, 0, "Vera-Bold")
    addMapping("Vera", 0, 1, "Vera-Italic")
    addMapping("Vera", 1, 1, "Vera-BoldItalic")
    return "Vera", "Vera-Bold", "Vera-Italic"


def _pseudonym_keys(run: PipelineRun) -> dict[str, str]:
    """Tipo de clave de seudónimos de la última ejecución de cada lote (en orden cronológico)."""
    keys: dict[str, str] = {}
    for op in run.operations:
        for gate in op["gates"]:
            res = gate["result"]
            key = res.get("extra", {}).get("pseudonym_key")
            if key:
                keys[res["subject"]] = key
    return keys


def build_story(g: Graph, run: PipelineRun, conforms: bool, labels: dict | None = None) -> list:
    """Contenido del reporte, separado de la escritura del PDF para poder probarlo."""
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import CondPageBreak, PageBreak, Paragraph, Spacer, Table, TableStyle

    font, bold, _ = _register_fonts()
    base = getSampleStyleSheet()["BodyText"]
    body = base.clone("cuerpo", fontName=font, fontSize=9, leading=12.5, spaceAfter=4)
    note = body.clone("nota", fontSize=7.5, leading=10, textColor=colors.HexColor("#444444"))
    cell = body.clone("celda", fontSize=7.5, leading=9.5, spaceAfter=0)
    head = cell.clone("encabezado", fontName=bold, textColor=colors.white)
    h0 = body.clone("titulo", fontName=bold, fontSize=17, leading=21, spaceAfter=8,
                    textColor=colors.HexColor(HEADER))
    h1 = body.clone("seccion", fontName=bold, fontSize=11.5, leading=14, spaceBefore=11, spaceAfter=5,
                    textColor=colors.HexColor(HEADER))
    h2 = h1.clone("subseccion", fontSize=9.5, leading=12, spaceBefore=8, spaceAfter=4)

    variables = (labels or {}).get("variables", {})
    notes = (labels or {}).get("notas", [])
    story: list = []

    def label(name):
        return variables.get(name, name) if name else "—"

    def h(text, style=h1):
        # Evita un título suelto al pie sin mover a otra página toda la tabla que le sigue
        story.append(CondPageBreak(3 * cm))
        story.append(Paragraph(escape(text), style))

    def p(text, style=body):  # el texto puede traer marcado: los valores se escapan antes de llamarla
        story.append(Paragraph(text, style))

    def as_cell(value, style=cell):
        text = value if isinstance(value, Markup) else escape(str(value))
        return Paragraph(text, style)

    def table(header, rows, widths):
        data = [[as_cell(c, head) for c in header]] + [[as_cell(c) for c in r] for r in rows]
        t = Table(data, colWidths=[w * cm for w in widths], repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(HEADER)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(ZEBRA)]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(GRID)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.2 * cm))

    def rule_rows(rows):
        return [[f"{m['contractId']} v{m['version']}", _subject(m["subject"]), m["ruleId"],
                 METRIC.get(m.get("metric"), m.get("metric") or "—"),
                 label(m.get("attribute")), _fmt(m["value"]),
                 f"[{_fmt(m.get('ciLow'))}; {_fmt(m.get('ciHigh'))}]" if m.get("ciLow") is not None else "—",
                 _fmt(m["decision"]), _threshold(m["operator"], m["threshold"]),
                 SEVERITY.get(m["severity"], m["severity"]), _rule_result(m)] for m in rows]

    rule_header = ["Contrato", "Evaluado", "Regla", "Qué mide", "Atributo", "Valor", "IC 95 %",
                   "Valor de decisión", "Umbral", "Severidad", "Resultado"]
    rule_widths = [1.8, 3.0, 2.6, 4.7, 2.0, 1.5, 3.1, 1.8, 1.7, 2.1, 2.0]  # suman el ancho útil: 26,2 cm

    # ----------------------------------------------------------- datos (última ejecución de cada sujeto)
    all_meds = run_query(g, "MEDICIONES")
    latest = latest_executions(all_meds)
    meds = [m for m in all_meds if m["timestamp"] == latest[(m["contractId"], m["subject"])]]
    executions = {(m["contractId"], m["subject"], m["timestamp"]) for m in all_meds}
    earlier = len(executions) - len(latest)
    gates = {(m["contractId"], m["subject"]): m["gatePassed"] for m in meds}
    dev = [m for m in meds if m["contractId"] != "C4"]
    ops = [m for m in meds if m["contractId"] == "C4"]
    op_subjects = sorted({m["subject"] for m in ops})

    # Con remediación, el modelo base puede fallar y el remediado aprobar: el C3 pasa si alguno aprueba.
    stopped = any(not ok for (cid, _), ok in gates.items() if cid in ("C1", "C2"))
    c3 = [ok for (cid, _), ok in gates.items() if cid == "C3"]
    verdict = "DETENIDO" if stopped or (c3 and not any(c3)) else ("APROBADO" if c3 else "INCOMPLETO")

    pc1 = [r for r in run_query(g, "PC1") if r["timestamp"] == latest.get((r["contractId"], r["subject"]))]
    pc2 = run_query(g, "PC2")
    pc4 = [r for r in run_query(g, "PC4") if r["time"] == latest.get(("C4", r["subject"]))]
    pc5 = run_query(g, "PC5")
    reasons = [r for r in run_query(g, "RAZONES") if r["time"] == latest.get(("C4", r["subject"]))]
    applicants = {(r["subject"], r["applicant"]) for r in reasons}
    bias_alerts = sum(r["alertType"] == "sesgo" for r in pc4)
    keys = _pseudonym_keys(run)
    ephemeral = any(keys.get(s) == "efímera" for s in {r["subject"] for r in reasons})

    # ----------------------------------------------------------------------------------------- resumen
    h(f"Reporte de cumplimiento de equidad — {run.dataset}", h0)
    tone = {"APROBADO": COLOR_OK, "DETENIDO": COLOR_FAIL}.get(verdict, COLOR_WARN)
    if bias_alerts:
        operation = f"; {bias_alerts} de {len(op_subjects)} lotes de producción con deriva del sesgo"
    elif op_subjects:
        operation = f"; sin deriva del sesgo en {len(op_subjects)} lotes de producción"
    else:
        operation = "; aún no se evaluaron lotes de producción"
    p(f'Resultado del pipeline (C1 a C3): <font color="{tone}"><b>{verdict}</b></font>{operation}.')

    summary = []
    for cid, purpose in CONTRACTS.items():
        rows = [m for m in meds if m["contractId"] == cid]
        if not rows:
            summary.append([cid, purpose, "—", "—", "—", "—", _colored("No ejecutado", COLOR_WARN)])
            continue
        failed = sum(not m["passed"] and m["severity"] == "block" for m in rows)
        warned = sum(not m["passed"] and m["severity"] != "block" for m in rows)
        ok = [v for (c, _), v in gates.items() if c == cid]
        if cid == "C4":
            state = _colored("Sin deriva del sesgo", COLOR_OK) if all(ok) else _colored("Con deriva del sesgo", COLOR_FAIL)
        elif cid == "C3" and any(ok) and not all(ok):
            state = _colored("Cumple tras remediación", COLOR_WARN)
        elif all(ok):
            state = _colored("Cumple", COLOR_OK)
        else:
            state = _colored("No cumple", COLOR_FAIL)
        summary.append([f"{cid} v{rows[0]['version']}", purpose, len(rows), failed, warned,
                        len({m["subject"] for m in rows}), state])
    table(["Contrato", "Qué verifica", "Reglas evaluadas", "Bloqueantes incumplidas", "Advertencias",
           "Sujetos evaluados", "Estado"], summary, [2.0, 9.3, 2.2, 2.7, 2.6, 2.2, 5.2])

    model = "—"
    if pc2:
        model = (f"{pc2[0]['registeredAs']} · {_stage(pc2[0]['stage'])} · exactitud balanceada "
                 f"{_fmt(pc2[0].get('balancedAccuracy'))}")
    facts = [
        ("Ejecución del pipeline (MLflow)", run.run_id),
        ("Lote de entrenamiento", f"hash DVC {run.batch_hash} · {_int(run.records_count)} registros"),
        ("Modelo aprobado", model),
        ("Remediación", METHOD.get(pc5[0]["method"], pc5[0]["method"]) if pc5 else "No se aplicó"),
        ("Alertas de deriva", _int(len(pc4))),
        ("Solicitantes rechazados con razones registradas", _int(len(applicants))),
        ("Conformidad del grafo con las formas SHACL", "Conforma" if conforms else "NO conforma"),
        ("Fecha de generación", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
    ]
    table(["Dato", "Valor"], facts, [8.5, 17.7])
    if earlier:
        omitted = "se omite 1 ejecución anterior, que sigue registrada" if earlier == 1 else (
            f"se omiten {earlier} ejecuciones anteriores, que siguen registradas")
        p(f"El monitor evaluó más de una vez algunos lotes: se muestra la última ejecución de cada uno y "
          f"{omitted} en el grafo.")
    p("<b>Alcance.</b> Este reporte certifica el cumplimiento de los contratos de equidad declarados y la "
      "consistencia estructural del registro. Aporta evidencia para la auditoría, pero no certifica el "
      "cumplimiento legal, que requiere una evaluación jurídica.", note)

    # ------------------------------------------------------------------------------------ 1. desarrollo
    story.append(PageBreak())
    h("1. Desarrollo: resultado de las compuertas C1 a C3")
    if dev:
        table(rule_header, rule_rows(dev), rule_widths)
        p("El <b>valor de decisión</b> es el que se compara con el umbral. Según la regla, es el valor observado "
          "o un extremo del intervalo de confianza. En el C3, las reglas con sufijo IC comparan el peor extremo: "
          "si no cumple, la regla advierte que la muestra no permite demostrar el cumplimiento, pero no bloquea.",
          note)
    else:
        p("No hay mediciones de las compuertas de desarrollo.")

    # ------------------------------------------------------------------------------------- 2. operación
    h("2. Operación: Contrato C4 por lote de producción")
    if op_subjects:
        records = {r["subject"]: r["records"] for r in run_query(g, "LOTES_OPERACION")}
        rows = []
        for s in op_subjects:
            lot = [m for m in ops if m["subject"] == s]
            n_reasons = len({a for subject, a in applicants if subject == s})
            passed = gates[("C4", s)]
            rows.append([_subject(s), _int(records[s]) if s in records else "—", len(lot),
                         sum(not m["passed"] and m["severity"] == "block" for m in lot),
                         sum(not m["passed"] and m["severity"] != "block" for m in lot), _int(n_reasons),
                         _colored("Sin deriva del sesgo", COLOR_OK) if passed
                         else _colored("Con deriva del sesgo", COLOR_FAIL)])
        table(["Lote", "Registros", "Reglas evaluadas", "Bloqueantes incumplidas", "Advertencias",
               "Solicitantes rechazados", "Estado"], rows, [4.0, 2.4, 2.6, 3.0, 2.6, 3.0, 8.6])
        p("El detalle de cada regla está en el Anexo A.", note)
    else:
        p("Aún no se evaluó ningún lote de producción con el C4.")

    # --------------------------------------------------------------------------------- 3 a 6. preguntas
    h("3. Reglas bloqueantes que no se cumplieron (PC1)")
    if pc1:
        table(["Contrato", "Regla", "Atributo", "Valor", "Valor de decisión", "Umbral", "Evaluado", "Paso"],
              [[r["contractId"], r["ruleId"], label(r.get("attribute")), _fmt(r["value"]), _fmt(r["decision"]),
                _threshold(r["operator"], r["threshold"]), _subject(r["subject"]), r.get("step") or "—"]
               for r in pc1], [2.0, 3.0, 3.5, 2.2, 2.8, 2.2, 5.6, 4.9])
    else:
        p("No se incumplió ninguna regla bloqueante.")

    h("4. Modelo aprobado y lote de entrenamiento (PC2)")
    if pc2:
        table(["Registrado como", "Versión", "Ejecución MLflow", "Exactitud balanceada", "Hash del lote", "Registros"],
              [[r["registeredAs"], _stage(r["stage"]), r["runId"], _fmt(r.get("balancedAccuracy")), r["hash"],
                _int(r["records"])] for r in pc2], [4.0, 3.0, 6.8, 2.6, 6.8, 3.0])
    else:
        p("Ningún modelo fue aprobado en esta ejecución.")

    h("5. Remediación: modelo base frente a remediado (PC5)")
    if pc5:
        p(f"Técnica: <b>{escape(METHOD.get(pc5[0]['method'], pc5[0]['method']))}</b>. Exactitud balanceada: "
          f"modelo base {_fmt(pc5[0].get('baseAcc'))}, modelo remediado {_fmt(pc5[0].get('remAcc'))}.")
        table(["Regla", "Atributo", "Modelo base", "¿Cumple?", "Modelo remediado", "¿Cumple?"],
              [[r["ruleId"], label(r.get("attribute")), _fmt(r["baseValue"]), _fmt(r["basePassed"]),
                _fmt(r["remValue"]), _fmt(r["remPassed"])] for r in pc5], [4.2, 5.5, 4.4, 3.3, 5.5, 3.3])
    else:
        p("No se aplicó remediación: el modelo base cumplió el contrato o el contrato no la declara.")

    h("6. Alertas de deriva del Contrato C4 (PC4)")
    if pc4:
        def rules_text(text):
            return re.sub(r"\[([^\]]+)\]", lambda m: f"[{label(m.group(1))}]", text) if text else "—"

        table(["Tipo", "Lote", "Registros", "Reglas incumplidas", "Reentrenamiento", "Fecha"],
              [[ALERT.get(r["alertType"], r["alertType"]), _subject(r["subject"]), _int(r["records"]),
                rules_text(r.get("rules")), _fmt(r.get("trigger")) if r["alertType"] == "sesgo" else "—",
                str(r["time"])[:19].replace("T", " ")] for r in pc4], [3.6, 2.6, 2.0, 10.2, 3.0, 4.8])
    elif op_subjects:
        p(f"Ninguno de los {len(op_subjects)} lotes de producción generó alertas de deriva.")
    else:
        p("Aún no se evaluó ningún lote de producción con el C4.")

    h("7. Razones de rechazo: resumen (PC3)")
    if reasons:
        p(f"Solicitantes rechazados con razones registradas: <b>{_int(len(applicants))}</b> "
          f"({_int(len(reasons))} factores). El detalle por solicitante está en el Anexo B.")
        first: dict[str, int] = {}
        for r in reasons:
            if r["rank"] == 1:
                first[r["feature"]] = first.get(r["feature"], 0) + 1
        table(["Variable", "Veces como factor principal", "% de los solicitantes"],
              [[label(f), _int(n), f"{_fmt(100 * n / len(applicants), 1)} %"]
               for f, n in sorted(first.items(), key=lambda kv: -kv[1])], [9.0, 5.0, 4.0])
    else:
        p("No hay razones de rechazo registradas: aún no se evaluó ningún lote o ningún solicitante fue rechazado.")

    # ------------------------------------------------------------------------------------------- anexos
    if ops:
        story.append(PageBreak())
        h("Anexo A. Contrato C4: detalle por regla y lote")
        table(rule_header, rule_rows(ops), rule_widths)
        p("<b>Por qué un valor por encima del umbral puede cumplir:</b> el C4 decide con el extremo más favorable "
          "del intervalo de confianza, de modo que solo alerta si todo el intervalo incumple el umbral. "
          "Evita falsas alarmas en lotes pequeños, a cambio de detectar menos desviaciones en ellos.", note)

    if reasons:
        story.append(PageBreak())
        h("Anexo B. Factores principales de cada solicitante rechazado (PC3)")
        p("Cada fila corresponde a una decisión de rechazo y muestra hasta tres variables con la mayor "
          "contribución negativa al resultado favorable según SHAP, de mayor a menor. Entre paréntesis está la "
          "contribución, en la escala interna del modelo: sirve para comparar los factores de un mismo solicitante. "
          "Estos <b>factores principales</b> describen cómo se formó la puntuación; no son relaciones causales y "
          "pueden cambiar con otro clasificador.")
        p("<b>Identificación.</b> El solicitante aparece solo por seudónimo. El reporte no incluye nombres, "
          "documentos ni los valores de sus variables. Este sistema registra las razones, pero no las comunica: "
          "responder a un pedido de motivos corresponde a la entidad, que conoce la identidad del solicitante y "
          "necesita un número de solicitud para vincular el pedido con la decisión.")
        if ephemeral:
            p(f'<font color="{COLOR_FAIL}"><b>Aviso: clave de seudónimos efímera.</b></font> Estos seudónimos no se '
              "pueden volver a vincular con los registros de origen. Para que se puedan vincular, hay que configurar "
              "la clave en FAIRGATE_PSEUDONYM_KEY antes de evaluar los lotes.")
        for text in notes:
            p(f"<b>Nota del caso.</b> {escape(str(text))}")
        p(f"Modelo que tomó las decisiones (ejecución MLflow): {escape(str(reasons[0]['modelRun']))}.", note)

        by_lot: dict[str, dict[str, list[dict]]] = {}
        for r in reasons:
            by_lot.setdefault(r["subject"], {}).setdefault(r["applicant"], []).append(r)
        for subject in sorted(by_lot):
            people = by_lot[subject]
            h(f"{_subject(subject)}: {_int(len(people))} solicitantes rechazados", h2)
            rows = []
            for applicant in sorted(people):
                factors = [f"{label(r['feature'])} ({_fmt(r['contribution'], 3)})"
                           for r in sorted(people[applicant], key=lambda r: r["rank"])]
                rows.append([applicant, *(factors + ["—"] * 3)[:3]])
            table(["Seudónimo", "Factor 1", "Factor 2", "Factor 3"], rows, [4.2, 7.3, 7.3, 7.4])
    return story


def write_pdf(g: Graph, run: PipelineRun, conforms: bool, path: Path, labels: dict | None = None) -> Path:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import SimpleDocTemplate

    story = build_story(g, run, conforms, labels)
    title = f"Reporte de cumplimiento de equidad — {run.dataset}"

    class NumberedCanvas(Canvas):
        """Espera al final del documento para conocer el total de páginas del pie."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                width = self._pagesize[0]
                self.setFont("Vera", 7)
                self.setFillColor(HexColor("#555555"))
                self.drawString(1.5 * cm, 0.8 * cm, title)
                self.drawRightString(width - 1.5 * cm, 0.8 * cm, f"Página {self._pageNumber} de {total}")
                super().showPage()
            super().save()

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.3 * cm, bottomMargin=1.4 * cm, title=title, lang="es")
    doc.build(story, canvasmaker=NumberedCanvas)
    return path


__all__ = ["add_report_node", "build_story", "latest_executions", "load_labels", "write_pdf", "QUERIES"]
