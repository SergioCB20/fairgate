# ADR-010: Agregar una cuarta compuerta (QA Gate 4, Contrato C4) para la deriva en producción

- **Fecha:** 2026-09-25 (decisión, aprobada con `estado/propuesta-diseno.md`) · redactado el 2026-09-27
- **Estado:** aceptada
- **Relacionado con:** Contrato C4 · Zona 3 · Cap. 1 (problema, O3, O4) · Cap. 4 (Tabla 11, 4.2.4, Figuras 4 y 7, 4.3.x "Contrato C4") · escenarios E5 y E6 · ADR-003, ADR-004, ADR-008

> **Nota:** este ADR se redactó después de la decisión. Reconstruye su justificación a partir de `estado/propuesta-diseno.md` (secciones 5, 6, 8 y 11), `estado/implementacion-vs-tesis.md` (sección 3) y el texto actual de los capítulos. En la propuesta no quedó escrita una justificación explícita del paso de 3 a 4 compuertas.

## Contexto
El diseño original tenía tres compuertas: C1 (datos crudos), C2 (transformadores) y C3 (modelo). La **Zona 3** (scoring y monitoreo) ya incluía Evidently para la deriva de datos y un *Trigger CT* de reentrenamiento, pero **ningún contrato de equidad**. Esto dejaba tres huecos:

1. **Hueco con el problema de la tesis.** El Cap. 1 plantea que la falta de validación en todo el ciclo, *"incluyendo la ingesta, el preprocesamiento, el entrenamiento y el monitoreo"*, produce una *"degradación silenciosa de la equidad"*, y el problema seleccionado incluye el *"monitoreo continuo"*. Con C1–C3, la equidad se valida solo hasta el despliegue; después, un modelo que se vuelve injusto por deriva no bloquea nada.
2. **Hueco con la evaluación (O4).** El protocolo experimental incluye deriva simulada (E5) y deriva real con HMDA (E6), y el Cap. 1 menciona la *"deriva en los lotes de producción"* entre los escenarios. Para medir la tasa de detección y la exactitud de localización de esos escenarios hace falta una compuerta que pueda detectarlos. Ni C1, ni C2, ni C3 se ejecutan sobre lotes de producción.
3. **Hueco en el *Trigger CT*.** Sin contrato, el reentrenamiento dependía de una "alerta de deriva" sin umbral ni severidad definidos, lo que contradice el principio de contratos declarativos y auditables (ADR-004).

Además, la implementación no tenía código de la Zona 3 (`estado/implementacion-vs-tesis.md`, sección 3), así que agregar una compuerta no obligaba a rehacer nada existente.

## Opciones consideradas
1. **Mantener 3 compuertas; la deriva solo como monitoreo (Evidently + alertas).** Es más simple y reduce el alcance. Pero la deriva del sesgo no tendría umbral ni severidad, no quedaría registrada como `GateExecution` en el linaje (ADR-007), y E5/E6 no tendrían una compuerta contra la cual medir la detección.
2. **Reusar el C3 en producción, sin contrato nuevo.** Se evita una pieza nueva. Pero el C3 es una postcondición del entrenamiento que incluye una remediación que reentrena el modelo (ADR-005; desde ADR-012, por reponderación), algo que no se puede aplicar a un lote en producción. Además, mezclaría dos puntos de control en una misma compuerta y perjudicaría la localización ("¿en qué etapa se detectó?").
3. **Crear un Contrato C4 / QA Gate 4 en la Zona 3**, con el mismo esquema YAML y el mismo motor (ADR-004), evaluado sobre cada lote puntuado.

## Decisión
**Opción 3.** El C4 es un **invariante de operación** que se evalúa sobre cada lote $B_t$ y tiene dos reglas:

| Regla | Definición | Umbral | Severidad |
|---|---|---|---|
| Deriva de datos | Proporción de variables con deriva según las pruebas de Evidently | ≤ 0,30 | `warn` |
| Deriva del sesgo | SPD, EOD y DI del C3, recalculados sobre $B_t$ con las etiquetas observadas | Los mismos del C3 | `block` → *Trigger CT* |

La deriva de datos solo se registra (`warn`), porque un cambio en la distribución no implica por sí mismo un daño en la equidad. La deriva del sesgo sí bloquea, porque es la degradación silenciosa que la tesis pretende evitar. Tener un contrato propio mantiene cada etapa en su compuerta: datos (C1), transformación (C2), modelo (C3) y producción (C4). Esto es lo que se mide como "etapa de detección" y "exactitud de localización" en O4. Sustento: Reda et al. (2025), quienes integran auditorías de *fairness* disparadas automáticamente y reentrenamiento por eventos dentro del ciclo MLOps.

## Consecuencias
- **Cambios en la tesis (ya aplicados):** la Tabla 11 pasa a C1–C4; se agregan el QA Gate 4 en 4.2.4 y en las Figuras 4 y 7, una sección "Contrato C4" en el Cap. 4 y el mecanismo de interrupción "común a C1–C4". En la comparación de O4, el "Nivel 0" no incluye el C4.
- **Trabajo derivado en el código:** scorer por lotes, captura y seudonimización del atributo protegido (art. 4 bis del AI Act, que sustituye al antiguo art. 10(5) desde el Reglamento (UE) 2026/1744), monitor de deriva del sesgo, `contracts/c4.yaml` y registro de la alerta en MLflow.
- **Supuesto de etiquetas retrasadas:** SPD y DI pueden calcularse sin etiquetas, pero **EOD necesita la etiqueta real**, y en crédito esa etiqueta llega meses después. En la tesis la operación es **simulada** (particiones de Davronov con deriva inyectada; HMDA año 1 → año 2), así que las etiquetas se tienen de inmediato. Esta limitación debe declararse.
- **Incertidumbre:** los lotes son más pequeños que el conjunto de prueba, así que las métricas por lote varían más. Por eso el C4 usa bootstrap y decide con el peor extremo del intervalo (ADR-008). Con lotes pequeños, el intervalo puede cruzar el umbral y bloquear con frecuencia, lo que hay que medir en E0.
- **Umbral de 0,30 sin calibrar:** la proporción máxima de variables con deriva es una decisión de diseño, no un valor tomado de una fuente. Queda como candidato a calibración, igual que los umbrales del C2 (ADR-006).
- **Inconsistencia de prioridad por resolver:** en `estado/propuesta-diseno.md` (sección 11), el C4 figura como **"Deseable"**, mientras que en el Cap. 4 aparece al mismo nivel que C1–C3. Si el C4 no llega a implementarse, habría que presentarlo en el Cap. 4 como trabajo diseñado pero no implementado y quitar E5/E6 de los escenarios obligatorios de O4. Esto lo decide el autor.
