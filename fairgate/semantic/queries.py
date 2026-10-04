"""Preguntas de competencia de la ontología (Cap. 4, 4.4.2) como consultas SPARQL."""
from __future__ import annotations

from rdflib import Graph

PREFIXES = """
PREFIX fair: <https://pucp.edu.pe/ontology/fair#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX dqv:  <http://www.w3.org/ns/dqv#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""

QUERIES: dict[str, tuple[str, str]] = {
    "PC1": (
        "¿Qué contrato y regla bloquearon, con qué valor e intervalo, y sobre qué se evaluó?",
        """
SELECT ?contractId ?ruleId ?attribute ?value ?ciLow ?ciHigh ?decision ?operator ?threshold ?subject ?step ?timestamp
WHERE {
  ?m a fair:FairnessMeasurement ;
     fair:measuresRule ?rule ;
     fair:rulePassed false ;
     prov:wasGeneratedBy ?exec ;
     dqv:value ?value ;
     fair:decisionValue ?decision .
  ?rule fair:ruleId ?ruleId ;
        fair:severity "block" ;
        fair:operator ?operator ;
        fair:threshold ?threshold ;
        fair:partOfContract/fair:contractId ?contractId .
  ?exec fair:subject ?subject ;
        prov:startedAtTime ?timestamp .
  OPTIONAL { ?m fair:concernsAttribute/fair:attributeName ?attribute }
  OPTIONAL { ?m fair:ciLow ?ciLow ; fair:ciHigh ?ciHigh }
  OPTIONAL { ?m fair:atStep/rdfs:label ?step }
}
ORDER BY DESC(?timestamp) ?contractId ?ruleId ?attribute
""",
    ),
    "PC2": (
        "¿Con qué lote (hash) se entrenó el modelo aprobado?",
        """
SELECT ?registeredAs ?stage ?runId ?balancedAccuracy ?hash ?records
WHERE {
  ?model a fair:ModelVersion ;
         fair:registeredAs ?registeredAs ;
         fair:modelStage ?stage ;
         fair:mlflowRunId ?runId ;
         prov:wasDerivedFrom+ ?batch .
  ?batch a fair:DataBatch ; fair:dvcHash ?hash ; fair:recordsCount ?records .
  OPTIONAL { ?model fair:balancedAccuracy ?balancedAccuracy }
}
""",
    ),
    "PC3": (
        "¿Qué razones de rechazo se comunicaron a cada solicitante?",
        """
SELECT ?applicant ?rank ?feature ?contribution ?modelRun
WHERE {
  ?r a fair:AdverseActionReason ;
     fair:applicantPseudoId ?applicant ;
     fair:rank ?rank ;
     fair:featureName ?feature ;
     fair:contribution ?contribution ;
     fair:explainsDecisionOf/fair:mlflowRunId ?modelRun .
}
ORDER BY ?applicant ?rank
""",
    ),
    "PC4": (
        "¿Qué alertas de deriva ocurrieron, sobre qué lote, por qué regla y si dispararon el reentrenamiento?",
        """
SELECT ?alertType ?time ?subject ?hash ?records ?trigger
       (GROUP_CONCAT(DISTINCT ?failed; separator=", ") AS ?rules)
WHERE {
  ?a a fair:DriftAlert ;
     fair:alertType ?alertType ;
     prov:generatedAtTime ?time ;
     prov:wasGeneratedBy ?exec ;
     fair:raisedOn ?b .
  ?b fair:dvcHash ?hash ; fair:recordsCount ?records .
  ?exec fair:subject ?subject .
  OPTIONAL { ?a fair:triggersRetraining ?trigger }
  OPTIONAL {
    ?m prov:wasGeneratedBy ?exec ; fair:rulePassed false ; fair:measuresRule ?rule .
    ?rule fair:ruleId ?ruleId ; fair:metricName ?metric .
    FILTER ((?alertType = "datos" && ?metric = "drift_share") || (?alertType = "sesgo" && ?metric != "drift_share"))
    OPTIONAL { ?m fair:concernsAttribute/fair:attributeName ?attr }
    BIND (IF(BOUND(?attr), CONCAT(?ruleId, "[", ?attr, "]"), ?ruleId) AS ?failed)
  }
}
GROUP BY ?alertType ?time ?subject ?hash ?records ?trigger
ORDER BY ?time ?alertType
""",
    ),
    "PC5": (
        "¿Cuál fue la diferencia de exactitud y de equidad entre el modelo base y el remediado?",
        """
SELECT ?method ?ruleId ?attribute ?baseValue ?remValue ?basePassed ?remPassed ?baseAcc ?remAcc
WHERE {
  ?rem a fair:Remediation ;
       fair:method ?method ;
       prov:wasInformedBy ?baseExec ;
       prov:generated ?remModel .
  ?baseExec prov:used ?baseModel .
  ?remExec a fair:GateExecution ; prov:used ?remModel .
  ?mb prov:wasGeneratedBy ?baseExec ; fair:measuresRule ?rule ; dqv:value ?baseValue ; fair:rulePassed ?basePassed .
  ?mr prov:wasGeneratedBy ?remExec ; fair:measuresRule ?rule ; dqv:value ?remValue ; fair:rulePassed ?remPassed .
  ?rule fair:ruleId ?ruleId .
  OPTIONAL { ?mb fair:concernsAttribute/fair:attributeName ?attrB }
  OPTIONAL { ?mr fair:concernsAttribute/fair:attributeName ?attrR }
  FILTER ((!BOUND(?attrB) && !BOUND(?attrR)) || ?attrB = ?attrR)
  BIND (COALESCE(?attrB, "") AS ?attribute)
  OPTIONAL { ?baseModel fair:balancedAccuracy ?baseAcc }
  OPTIONAL { ?remModel fair:balancedAccuracy ?remAcc }
}
ORDER BY ?ruleId ?attribute
""",
    ),
    # Consulta de apoyo del reporte: todas las mediciones, por compuerta.
    "MEDICIONES": (
        "Resultado de cada regla de cada ejecución de compuerta",
        """
SELECT ?contractId ?version ?subject ?gatePassed ?ruleId ?severity ?attribute ?value ?ciLow ?ciHigh ?decision ?operator ?threshold ?passed ?timestamp
WHERE {
  ?exec a fair:GateExecution ; fair:subject ?subject ; fair:gatePassed ?gatePassed ; prov:startedAtTime ?timestamp .
  ?m prov:wasGeneratedBy ?exec ; fair:measuresRule ?rule ; dqv:value ?value ;
     fair:decisionValue ?decision ; fair:rulePassed ?passed .
  ?rule fair:ruleId ?ruleId ; fair:severity ?severity ; fair:operator ?operator ; fair:threshold ?threshold ;
        fair:partOfContract ?c .
  ?c fair:contractId ?contractId ; fair:version ?version .
  OPTIONAL { ?m fair:concernsAttribute/fair:attributeName ?attribute }
  OPTIONAL { ?m fair:ciLow ?ciLow ; fair:ciHigh ?ciHigh }
}
ORDER BY ?timestamp ?ruleId ?attribute
""",
    ),
}


def run_query(g: Graph, name: str) -> list[dict]:
    _, sparql = QUERIES[name]
    rows = []
    for row in g.query(PREFIXES + sparql):
        rows.append({k: (None if v is None else v.toPython()) for k, v in row.asdict().items()})
    return rows
