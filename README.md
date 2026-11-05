# fairgate

Motor de **contratos de equidad** (QA Gates) para pipelines de aprendizaje supervisado. Es el prototipo de la tesis *"Validación de fairness en MLOps"*, correspondiente al Objetivo 3. Es un prototipo de investigación, no un producto: sirve para evaluar la arquitectura de compuertas, y cada organización debe declarar y recalibrar sus propios contratos.

Licencia MIT (`LICENSE`). **El repositorio no contiene datos:** los conjuntos de los casos de estudio se obtienen de su fuente y se rigen por sus propias licencias.

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
  explanations.py    Zona 3: razones de rechazo (factores principales SHAP) y su estabilidad
  remediation.py     catálogo: reponderación (Kamiran & Calders, 2012) ADR-012
  lineage.py         registro de cada ejecución en MLflow
  engine.py          orquestación C1 → C2 → C3 con interrupción (el C4 se evalúa en la operación)
  semantic/          Zona 4: ontology.ttl, shapes.ttl (SHACL), export.py (MLflow → RDF),
                     queries.py (PC1–PC5 en SPARQL), report.py (reporte PDF desde el grafo),
                     store.py (repositorio RDF: una ejecución por grafo con nombre)
  cli.py             `python -m fairgate validate|run|monitor|export|query|report <dominio>`
domains/davronov/    dataset.yaml + contratos c1.yaml, c2.yaml, c3.yaml, c4.yaml
domains/hmda/        caso de generalización (E6): HMDA de Delaware, 2022 (referencia) y 2023 (producción)
docs/adr/            decisiones de diseño (ADR-001 a ADR-020), citadas en el código y los contratos
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

El remoto DVC del autor es privado, así que `dvc pull` solo funciona con sus credenciales; quien reproduzca el trabajo debe seguir los pasos anteriores. El caso HMDA no necesita remoto: `python -m experiments preparar-hmda` lo descarga de la API de la FFIEC.

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
2. **Razones de rechazo** (`fairgate/explanations.py`): para cada solicitante rechazado, hasta `params.reason_top_k` variables (3 por defecto; 0 las desactiva) con la contribución SHAP más negativa al resultado favorable. Se denominan *factores principales*: describen la puntuación del modelo, no causas. Explicador lineal para la regresión logística y de árboles para los demás clasificadores del catálogo; las columnas one-hot se suman en su variable de origen. Se registran en MLflow (`rejection_reasons.json`) y llegan al grafo como `fair:AdverseActionReason` (PC3). `top_k_agreement` mide su estabilidad entre dos modelos (Cap. 6, 6.4).
3. Evalúa el C4:
   - **Deriva de datos (`warn`):** proporción de variables con deriva, con las pruebas que Evidently usa por defecto, implementadas con SciPy (ADR-016).
   - **Deriva del sesgo (`block`):** SPD, EOD y DI del C3 sobre el lote. Se alerta solo si todo el intervalo de confianza incumple el umbral (`decide_on: best_bound`, ADR-017). Sin etiquetas observadas, la EOD queda como "no aplica".
4. Si hay deriva del sesgo, registra la alerta y termina con **exit 1 (Trigger CT)**. El reentrenamiento consiste en volver a ejecutar el pipeline (`run`) con los datos nuevos; ese disparo automático no está implementado.

Con `--no-lineage`, el pipeline se ejecuta en memoria y se despliega el modelo que aprueba el C3. Davronov no tiene marcas temporales, así que la operación es **simulada**: los lotes son particiones aleatorias del conjunto de prueba, sin deriva inyectada (escenario de control). Su número se declara en `c4.yaml` (`params.batches`).

Cada ejecución de compuerta se registra en MLflow (`mlflow.db`): parámetros del contrato, hash del lote, valor e intervalo de cada regla, resultado y el JSON completo. El modelo aprobado se registra como `davronov-scoring`. Para ver el registro: `mlflow ui --backend-store-uri sqlite:///mlflow.db`. Para desactivarlo: `FAIRGATE_LINEAGE=0`.

### Trazabilidad semántica (Zona 4)

```bash
python -m fairgate export domains/davronov      # MLflow → RDF; valida con SHACL; escribe lineage/<dataset>-<hash>-<run>.ttl
python -m fairgate query domains/davronov PC1   # PC1..PC5 (preguntas de competencia) o MEDICIONES
python -m fairgate query domains/davronov PC1 --historial  # la misma pregunta sobre todo el repositorio RDF
python -m fairgate report domains/davronov      # grafo + reporte de cumplimiento en reports/*.pdf
```

El exportador lee **solo** de MLflow, con la última ejecución del pipeline o la indicada con `--run-id`. También incluye las ejecuciones de operación del modelo que esa ejecución aprobó: cada lote de producción (`fair:DataBatch`, con el hash de su contenido), su ejecución del C4 y las alertas `fair:DriftAlert`. El grafo reutiliza PROV-O y DQV (`fairgate/semantic/ontology.ttl`) y solo se incorpora al repositorio si conforma las formas SHACL (`shapes.ttl`, una por clase).

El **repositorio RDF** es el directorio `lineage/` (`fairgate/semantic/store.py`): cada ejecución del pipeline es un grafo con nombre, persistido como `<dataset>-<hash>-<run>.ttl`. Con `--historial`, la pregunta se responde sobre todas las ejecuciones y cada fila indica de cuál proviene (columna `ejecucion`). Los nodos compartidos (lotes, contratos, reglas y atributos) tienen el mismo IRI en todas las ejecuciones, así que `Repository.dataset()` los integra en la unión de los grafos para consultas SPARQL propias. El reporte PDF se construye con consultas SPARQL sobre el grafo y queda registrado en él como `fair:ComplianceReport`. Preguntas de competencia:

| | Pregunta |
|---|---|
| PC1 | ¿Qué contrato y regla bloquearon, con qué valor e intervalo, y en qué paso? |
| PC2 | ¿Con qué lote (hash) se entrenó el modelo aprobado? |
| PC3 | ¿Qué razones de rechazo se registraron para cada solicitante? |
| PC4 | ¿Qué alertas de deriva ocurrieron, sobre qué lote, por qué regla y si dispararon el reentrenamiento? |
| PC5 | ¿Cuál fue la diferencia de exactitud y de equidad entre el modelo base y el remediado? |

## Evaluación experimental (O4, `experiments/`)

Infraestructura del protocolo del Cap. 6. No forma parte del motor: usa sus compuertas sobre datos con sesgos inyectados.

```
experiments/
  protocol.py           escenarios E0–E5, intensidades, semillas y verdad de referencia (Tabla 20)
  scenarios.py          inyectores (subrepresentación, sustituta, transformador sesgado, etiquetas, deriva)
  runner.py             repeticiones: todas las compuertas sin detenerse; registro JSONL reanudable
  configs.py            B0, B2, P−C1, P−C2 y P (Tabla 21): detección, localización, etapa y tiempo
  stats.py              Wilson, McNemar exacta, Wilcoxon y Holm (6.2.4)
  analysis.py           reporte: tablas, pruebas pareadas, grilla del C4, equidad–utilidad, costo,
                        auditabilidad, sensibilidad del C2 y calibración del umbral de deriva (6.2.5)
  audit.py              6.4: grafo por repetición, fidelidad de las PC, pruebas negativas, linaje vs MLflow
  drift_export.py       6.2.6: exporta lotes para comparar con Evidently
  evidently_compare.py  6.2.6: comparación, en un entorno con Evidently (no importa fairgate)
  stability.py          6.4: estabilidad de las razones de rechazo entre semillas
  hmda.py               E6: descarga (API del Data Browser de la FFIEC) y preparación de HMDA
  e6.py                 E6: desarrollo con el año de referencia y C4 sobre los lotes del año siguiente
```

```bash
python -m experiments ejecutar --semillas humo --repeticiones 1 --auditoria   # verifica la infraestructura
python -m experiments ejecutar --semillas calibracion --escenarios E0,E5      # calibración del C4
python -m experiments congelar --nota "contratos revisados por el autor"     # antes de evaluar
python -m experiments ejecutar --semillas evaluacion --auditoria             # 30 repeticiones (6.2.4)
python -m experiments ejecutar --semillas evaluacion --escenarios E0,E4,E5 --clasificador hist_gradient_boosting
python -m experiments analizar experiments/resultados/evaluacion-dataset.jsonl
python -m experiments auditar-linaje --semilla 9000                           # negativas y linaje vs MLflow
python -m experiments estabilidad --semillas evaluacion                       # razones de rechazo (6.4)
python -m experiments preparar-hmda                                           # E6: descarga y prepara HMDA
python -m experiments congelar --dominio domains/hmda --nota "..."
python -m experiments e6 --semillas evaluacion                                # E6: deriva real
```

Semillas: desarrollo 42, calibración 1000–1029, evaluación 2000–2029, humo 9000–9002. **La evaluación solo se ejecuta con los contratos congelados** (`experiments/congelamiento.json`, con el hash de cada YAML del dominio; `congelamiento-hmda.json` para el E6). Los registros quedan en `experiments/resultados/`. De ahí se versionan los resúmenes (`evaluacion-dataset.md`, `evaluacion-hist_gradient_boosting.md`, `calibracion-dataset.md`, `e6-evaluacion-dataset.md` y `estabilidad-*.json`); los registros por repetición (`.jsonl`) se publican como activo del *release* `resultados-articulo`.

## Reproducir los resultados del artículo

Hay dos caminos. El primero no necesita ejecutar nada pesado; el segundo regenera todo desde cero.

**A. Regenerar las tablas a partir de los registros publicados** (minutos).

1. Instalar el entorno (sección *Instalación*).
2. Descargar `fairgate-resultados-articulo.zip` del *release* `resultados-articulo` y descomprimirlo en `experiments/resultados/`. Contiene los registros `.jsonl` de calibración, evaluación (regresión logística y *gradient boosting*), E6 y las pruebas de humo (solo métricas agregadas por repetición, sin filas del dataset).
3. Ejecutar `python -m experiments analizar experiments/resultados/evaluacion-dataset.jsonl`. El resultado coincide con `experiments/resultados/evaluacion-dataset.md` salvo 2 de sus 991 líneas (E4R con intensidad 0,05, solo 2 detecciones), donde la etiqueta de la etapa puede salir como `modelo` en lugar de `operacion`. Las cifras de detección, localización y los intervalos son idénticos.

**B. Re-ejecutar la evaluación completa** (varias horas).

1. Instalar el entorno y obtener los datos: Davronov desde Kaggle (con la verificación del *hash*) y HMDA con `python -m experiments preparar-hmda`.
2. Comprobar que los contratos son los congelados: `experiments/congelamiento.json` y `experiments/congelamiento-hmda.json` guardan el *hash* de cada YAML, y las semillas de evaluación solo se ejecutan si coinciden. La comparación no depende del fin de línea (LF o CRLF): el congelamiento se hizo en Windows y registró algunos YAML con una terminación y otros con la otra, y los YAML de `domains/` se entregan con LF (`.gitattributes`).
3. Ejecutar los comandos de la sección *Evaluación experimental*, en el orden indicado (las semillas de calibración y de evaluación están fijadas en `experiments/protocol.py`).

Las cifras del artículo salen de `evaluacion-dataset.md` (1 170 repeticiones con regresión logística), `evaluacion-hist_gradient_boosting.md` (870 repeticiones), `calibracion-dataset.md` y `e6-evaluacion-dataset.md` (HMDA). Los resultados dependen de la versión de las dependencias: usar siempre `requirements.lock.txt`.

## Decisiones de diseño

`docs/adr/` reúne los registros de decisión (ADR-001 a ADR-020) a los que remiten el código, los contratos y este archivo. El ADR-020 explica por qué el repositorio es público pero no contiene datos.

## Cómo citar

Chumbimuni, S. (2026). *fairgate: contratos de equidad para la validación continua de pipelines MLOps* (v0.1.0) [Software]. https://github.com/SergioCB20/fairgate

## Licencia

MIT. Ver `LICENSE`. Los datos de los casos de estudio no se incluyen ni se relicencian.

## CI (GitHub Actions)

- `motor`: valida los contratos y ejecuta `tests/unit`. Siempre corre.
- `compuertas-davronov`: descarga el dataset con `dvc pull` y ejecuta `tests/gates`: C1 a C3 sobre el pipeline y C4 sobre la operación simulada, donde no debe haber alertas. Después ejecuta tres repeticiones del control (E0, semillas de humo) para medir el costo de cada compuerta en GitHub Actions (Cap. 6, 6.2.3), y guarda el linaje, el reporte y ese registro como artefactos. Solo corre si el repositorio tiene los *secrets* `DAGSHUB_USER` y `DAGSHUB_TOKEN` (usuario y token) de un remoto DVC **privado** (por ejemplo, un repositorio privado de DagsHub configurado como remoto `origin`). En una copia del repositorio sin esos *secrets*, este trabajo se omite y solo corre `motor`.

## Estado (etapas de ADR-014)

- [x] Etapa 1: motor, C1–C3, reponderación, MLflow y CI.
- [x] Etapa 2: capa semántica (RDF, SHACL, SPARQL, reporte).
- [x] Etapa 3: C4 y Zona 3 (2026-10-03), razones de rechazo con SHAP y repositorio RDF del historial (2026-10-14); escenarios E0–E5 evaluados (2026-10-15).
- [x] Etapa 4: HMDA (E6, 2026-10-15). Exigió un cambio en el motor: la reponderación ahora admite registros que no pertenecen a ningún grupo protegido (solicitudes conjuntas).
