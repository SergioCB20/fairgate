# ADR-014: Nuevo repositorio para el prototipo (`fairgate`)

- **Fecha:** 2026-09-28
- **Estado:** aceptada (decisión del autor)
- **Relacionado con:** O3 · R.E.3.1, R.E.3.2, R.E.3.3 · Cap. 5 · ADR-001 a ADR-013

## Contexto
El prototipo antiguo (`mlops-fairness-scoring`, 17 commits, unas 780 líneas) implementaba la arquitectura anterior al rediseño del 2026-09-25 y a las decisiones de ADR-004 a ADR-013. Una revisión completa del código mostró lo siguiente:

- **No existe el núcleo del diseño.** No hay motor de contratos ni esquema común (ADR-004): cada test lee su propio YAML con claves distintas.
- **Las compuertas no siguen el diseño vigente:**
  - C1 solo evalúa `Sex`, y `Age` es variable del modelo (contradice ADR-013).
  - C2 usa información mutua por variable sobre la salida final, sin localizar el paso (contradice ADR-006).
  - C3 no usa *bootstrap* (ADR-008), trata el DI como rango [0,8; 1,25] (ADR-005), mitiga con `ThresholdOptimizer` (reemplazado por ADR-012) y ejecuta el modelo base en CI con `continue-on-error`.
- **Faltan las Zonas 3 y 4:** sus carpetas están vacías y MLflow ni se importa.
- **No es reproducible:** las dependencias no están fijadas (contradice ADR-009), no hay README y los tests dependen del directorio de trabajo.
- **Incumple la licencia:** el repositorio de GitHub es **público** (verificado con la API de GitHub el 2026-09-28) y el CSV de Davronov está en su historial (commit `f3977fa`), pese a ADR-009.

## Opciones consideradas
1. **Refactorizar el repositorio antiguo.** Casi todos los archivos cambian; además, el historial conserva el CSV.
2. **Repositorio nuevo, conservando el antiguo archivado y privado.** Se parte de una estructura que separa el motor genérico de la configuración de cada dominio. El historial nace sin datos.

## Decisión
**Opción 2.** Se crea el proyecto `fairgate` (`fairgate`), con esta estructura:

- `fairgate/`: motor genérico, independiente del dominio. Incluye el esquema (pydantic), el motor, las métricas con *bootstrap*, las compuertas C1–C3, el catálogo de remediación (reponderación) y el registro en MLflow.
- `domains/<dataset>/`: especificación del *dataset* y contratos YAML (Davronov primero; HMDA después).
- `tests/`: pruebas unitarias del motor con datos sintéticos, que no necesitan el *dataset*, y pruebas de las compuertas parametrizadas por regla y atributo, que se omiten si el *dataset* no está disponible.
- Dependencias fijadas en `requirements.lock.txt`. Los datos nunca se versionan en Git (solo el `.dvc`).

Implementación por etapas:
1. Motor, C1–C3, reponderación, MLflow y CI (R.E.3.1 y la mayor parte del R.E.3.2).
2. Capa semántica: RDF, SHACL, SPARQL y reporte (R.E.3.3).
3. C4 y escenarios E0–E6, sujeto a la prioridad del C4 (ADR-010).
4. HMDA.

Se reutilizan del proyecto antiguo el constructor de esquemas Pandera, la lista de columnas con fuga, la idea de las pruebas negativas con datos sintéticos, el esqueleto del workflow y las llamadas a Fairlearn.

## Consecuencias
- El repositorio antiguo se conserva **privado y archivado** como evidencia de la primera iteración. ADR-001 y ADR-005 citan sus commits.
- **Acciones del autor:** hacer privado el repositorio antiguo; crear en GitHub un repositorio **privado** para `fairgate` y subirlo; configurar un remoto DVC privado y los *secrets* de CI para que las compuertas con datos reales se ejecuten en GitHub Actions. Sin esos *secrets*, el CI solo ejecuta las pruebas unitarias del motor.
- Los resultados reportados en el README antiguo (por ejemplo, "18 pp → cumple tras `ThresholdOptimizer`") corresponden al diseño anterior. El Cap. 5 debe reportar los resultados del nuevo proyecto.
