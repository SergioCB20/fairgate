# Decisiones (ADRs)

Registro de decisiones de arquitectura y metodología. Cada ADR sigue `template-adr.md`: contexto, opciones consideradas, decisión y consecuencias.

| ADR | Decisión | Estado | Fecha |
|---|---|---|---|
| [001](ADR-001-exclusion-marital-proxy-sex.md) | Excluir `Marital` por ser proxy de `Sex` | aceptada | 2026-09-16 |
| [002](ADR-002-csv-en-git-para-ci.md) | CSV en Git para el CI (workaround de DVC 3.67.1) | reemplazada por 009 (publicación del dataset) | 2026-09-19 |
| [003](ADR-003-datasets-davronov-principal-hmda-secundario.md) | Davronov como principal, HMDA como secundario; `Age_group` como segundo atributo protegido | aceptada | 2026-09-25 |
| [004](ADR-004-motor-de-contratos-generico.md) | Motor de contratos genérico con esquema declarativo común | aceptada | 2026-09-25 |
| [005](ADR-005-remediacion-explicita-en-c3.md) | Remediación explícita en el C3; DI direccional o simétrico | aceptada (técnica reemplazada por 012) | 2026-09-25 |
| [006](ADR-006-c2-por-transformador-con-auc.md) | C2 por transformador con AUC de un clasificador auxiliar | aceptada (umbrales por calibrar) | 2026-09-25 |
| [007](ADR-007-trazabilidad-sin-interpretme.md) | Trazabilidad MLflow → RDFLib con PROV-O/DQV/SHACL, sin InterpretME | aceptada | 2026-09-25 |
| [008](ADR-008-bootstrap-en-las-compuertas.md) | Decisión de las compuertas con IC bootstrap | aceptada (regla del C4 modificada por 017) | 2026-09-25 |
| [009](ADR-009-repositorios-privados-por-licencia.md) | Repositorios privados y ejecución "reproducible local y en CI" | aceptada (visibilidad de `fairgate` reemplazada por 020) | 2026-09-25 |
| [010](ADR-010-qa-gate-4-deriva-en-produccion.md) | Cuarta compuerta (QA Gate 4, C4) para la deriva de datos y del sesgo en producción | aceptada; implementada el 2026-10-03 (ver 016 y 017) | 2026-09-25 |
| [011](ADR-011-seleccion-de-metricas-de-equidad.md) | SPD, EOD y DI como reglas; métricas individuales fuera de las compuertas | aceptada | 2026-09-27 |
| [012](ADR-012-remediacion-sin-atributo-protegido-en-inferencia.md) | Remediación del C3 por reponderación, sin atributo protegido en la inferencia; catálogo de técnicas | aceptada | 2026-09-28 |
| [013](ADR-013-fuentes-del-atributo-protegido-y-politica-de-variables.md) | Columnas de origen de los atributos protegidos y política de uso como variable (C1 y C2) | aceptada | 2026-09-28 |
| [014](ADR-014-nuevo-repositorio-del-prototipo.md) | Nuevo repositorio `fairgate` para el prototipo; el antiguo queda privado y archivado | aceptada | 2026-09-28 |
| [015](ADR-015-deteccion-de-fuga-de-la-etiqueta-en-c1.md) | Regla C1-LEAK (fuga de la etiqueta no declarada); `Field` y `Changed_phone_number` como columnas con fuga | aceptada (validar) | 2026-09-28 |
| [016](ADR-016-pruebas-de-deriva-con-scipy.md) | Pruebas de deriva de datos del C4 con el criterio de Evidently, implementadas con SciPy | aceptada; equivalencia con Evidently verificada el 2026-10-14 | 2026-10-03 |
| [017](ADR-017-c4-decide-con-el-mejor-extremo.md) | El C4 alerta solo si todo el intervalo incumple el umbral (mejor extremo) | aceptada | 2026-10-03 |
| [018](ADR-018-c3-decide-con-el-valor-y-advierte-con-el-intervalo.md) | El C3 bloquea con el valor puntual y advierte cuando el intervalo cruza el umbral | aceptada (validar) | 2026-10-14 |
| [019](ADR-019-configuracion-del-caso-hmda.md) | Configuración del caso HMDA (E6): Delaware 2022/2023, atributos, fugas, exclusiones y umbrales | aceptada (validar) | 2026-10-15 |
| [020](ADR-020-fairgate-publico-sin-datos.md) | `fairgate` público, sin datos y con licencia MIT | aceptada | 2026-11-05 |

Estos ADR documentan las decisiones de diseño del prototipo `fairgate`. Su texto completo y el contexto de la tesis están en el repositorio de la tesis.
