# fairgate

Motor de **contratos de equidad** (QA Gates) para pipelines de aprendizaje supervisado. Es el prototipo de la tesis *"Validación de fairness en MLOps"*, correspondiente al Objetivo 3.

El motor es **genérico** para clasificación binaria sobre datos tabulares. Todo lo que depende del caso de estudio se declara en YAML dentro de `domains/<caso>/`: columnas, etiqueta y valor favorable, clasificador base (catálogo: `logistic_regression`, `random_forest`, `hist_gradient_boosting`), atributos protegidos, sus columnas de origen, métricas, umbrales y técnica de remediación. Para aplicar el sistema a otro dataset del crédito o a otro rubro se agrega una carpeta nueva, sin cambiar código. Regresión, clasificación multiclase, *ranking* y datos no tabulares quedan fuera de alcance.

## Estructura

```
fairgate/            motor genérico
  schema.py          esquema declarativo común (pydantic)             ADR-004, ADR-013
  data.py            carga del dominio y del lote, hash DVC, grupos protegidos
  metrics.py         SPD, EOD, DI (direccional/simétrica) + bootstrap ADR-008, ADR-011
  preprocessing.py   pasos imputación → escalado → codificación      ADR-006
  gates.py           C1 (datos), C2 (filtración por paso), C3 (modelo + remediación)
  monitoring.py      Zona 3: scorer por lotes, seudonimización, deriva de datos y del sesgo, C4   ADR-010, ADR-016, ADR-017
  remediation.py     catálogo: reponderación (Kamiran & Calders, 2012) ADR-012
  lineage.py         registro de cada ejecución en MLflow
  engine.py          orquestación C1 → C2 → C3 con interrupción (el C4 se evalúa en la operación)
  semantic/          Zona 4: ontology.ttl, shapes.ttl (SHACL), export.py (MLflow → RDF),
                     queries.py (PC1–PC5 en SPARQL), report.py (reporte PDF desde el grafo)
  cli.py             `python -m fairgate validate|run|monitor|export|query|report <dominio>`
domains/davronov/    dataset.yaml + contratos c1.yaml, c2.yaml, c3.yaml, c4.yaml
tests/unit/          pruebas del motor con datos sintéticos (no necesitan el dataset)
tests/gates/         una prueba por regla × atributo sobre el dataset real
```

## Instalación (Python 3.11)

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.lock.txt
pip install -e . --no-deps
```

`requirements.lock.txt` fija la versión exacta de todas las dependencias. Debe usarse igual en local y en CI.

## Obtención del dataset (Davronov)

La licencia del dataset es *"Data files © Original Authors"*, así que **no se redistribuye y no se versiona en Git**.

1. Descargar "Credit-scoring data" desde Kaggle: https://www.kaggle.com/datasets/islombekdavronov/creditscoring-data (requiere una cuenta).
2. Copiar el CSV a `data/davronov/credit-scoring.csv`.
3. Verificar que es el mismo lote: `python -c "from fairgate.data import file_hash; from pathlib import Path; print(file_hash(Path('data/davronov/credit-scoring.csv')))"` debe devolver `1aa87791dbf04be9e8440f4eef1ebc54`, el mismo hash que registra `data/davronov/credit-scoring.csv.dvc`.

Con un remoto DVC privado configurado, basta con `dvc pull`.

## Uso

```bash
python -m fairgate validate domains/davronov   # valida contratos (sin datos)
python -m fairgate run domains/davronov        # C1 → C2 → C3; exit 1 si una regla 'block' falla
pytest tests/unit                              # motor
pytest tests/gates -v                          # una prueba por regla y atributo protegido
```

### Operación (Zona 3, Contrato C4)

```bash
python -m fairgate monitor domains/davronov              # operación simulada: lotes del conjunto de prueba
python -m fairgate monitor domains/davronov lote1.csv    # lotes de producción propios (CSV)
```

El monitor carga la última versión de `<dataset>-scoring` desde el registro de MLflow (Trigger CD) y, por cada lote:

1. Asigna a cada registro un seudónimo (HMAC-SHA256 con la clave `FAIRGATE_PSEUDONYM_KEY`; sin ella, la clave es efímera) y separa el atributo protegido y la etiqueta en almacenes propios. El scorer recibe solo las variables del modelo.
2. Evalúa el C4:
   - **Deriva de datos (`warn`):** proporción de variables con deriva, con las pruebas que Evidently usa por defecto, implementadas con SciPy (ADR-016).
   - **Deriva del sesgo (`block`):** SPD, EOD y DI del C3 sobre el lote. Se alerta solo si todo el intervalo de confianza incumple el umbral (`decide_on: best_bound`, ADR-017). Sin etiquetas observadas, la EOD queda como "no aplica".
3. Si hay deriva del sesgo, registra la alerta y termina con **exit 1 (Trigger CT)**. El reentrenamiento consiste en volver a ejecutar el pipeline (`run`) con los datos nuevos; ese disparo automático no está implementado.

Con `--no-lineage`, el pipeline se ejecuta en memoria y se despliega el modelo que aprueba el C3. Davronov no tiene marcas temporales, así que la operación es **simulada**: los lotes son particiones aleatorias del conjunto de prueba, sin deriva inyectada (escenario de control). Su número se declara en `c4.yaml` (`params.batches`).

Cada ejecución de compuerta se registra en MLflow (`mlflow.db`): parámetros del contrato, hash del lote, valor e intervalo de cada regla, resultado y el JSON completo. El modelo aprobado se registra como `davronov-scoring`. Para ver el registro: `mlflow ui --backend-store-uri sqlite:///mlflow.db`. Para desactivarlo: `FAIRGATE_LINEAGE=0`.

### Trazabilidad semántica (Zona 4)

```bash
python -m fairgate export domains/davronov      # MLflow → RDF; valida con SHACL; escribe lineage/<dataset>-<hash>-<run>.ttl
python -m fairgate query domains/davronov PC1   # PC1..PC5 (preguntas de competencia) o MEDICIONES
python -m fairgate report domains/davronov      # grafo + reporte de cumplimiento en reports/*.pdf
```

El exportador lee **solo** de MLflow, con la última ejecución del pipeline o la indicada con `--run-id`. También incluye las ejecuciones de operación del modelo que esa ejecución aprobó: cada lote de producción (`fair:DataBatch`, con el hash de su contenido), su ejecución del C4 y las alertas `fair:DriftAlert`. El grafo reutiliza PROV-O y DQV (`fairgate/semantic/ontology.ttl`) y solo se escribe si conforma las formas SHACL (`shapes.ttl`, una por clase). El reporte PDF se construye con consultas SPARQL sobre el grafo y queda registrado en él como `fair:ComplianceReport`. Preguntas de competencia:

| | Pregunta |
|---|---|
| PC1 | ¿Qué contrato y regla bloquearon, con qué valor e intervalo, y en qué paso? |
| PC2 | ¿Con qué lote (hash) se entrenó el modelo aprobado? |
| PC3 | ¿Qué razones de rechazo se comunicaron a cada solicitante? (Zona 3, etapa 3) |
| PC4 | ¿Qué alertas de deriva ocurrieron, sobre qué lote, por qué regla y si dispararon el reentrenamiento? |
| PC5 | ¿Cuál fue la diferencia de exactitud y de equidad entre el modelo base y el remediado? |

## CI (GitHub Actions)

- `motor`: valida los contratos y ejecuta `tests/unit`. Siempre corre.
- `compuertas-davronov`: descarga el dataset con `dvc pull` y ejecuta `tests/gates`: C1 a C3 sobre el pipeline y C4 sobre la operación simulada, donde no debe haber alertas. Solo corre si el repositorio tiene los *secrets* `DAGSHUB_USER` y `DAGSHUB_TOKEN` (usuario y token) de un remoto DVC **privado** (por ejemplo, un repositorio privado de DagsHub configurado como remoto `origin`).

## Estado (etapas de ADR-014)

- [x] Etapa 1: motor, C1–C3, reponderación, MLflow y CI.
- [x] Etapa 2: capa semántica (RDF, SHACL, SPARQL, reporte).
- [ ] Etapa 3: C4 y Zona 3 (hecho el 2026-10-03, salvo las razones de rechazo con SHAP); escenarios E0–E6 (pendientes).
- [ ] Etapa 4: HMDA.
