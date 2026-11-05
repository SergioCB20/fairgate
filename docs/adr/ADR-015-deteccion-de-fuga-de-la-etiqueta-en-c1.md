# ADR-015: Detección automática de fuga de la etiqueta en el C1; `Field` y `Changed_phone_number` como columnas con fuga

- **Fecha:** 2026-09-28
- **Estado:** aceptada (tomada durante la etapa 1 de `fairgate`; **validar con el autor**)
- **Relacionado con:** Contrato C1 · Cap. 4 (4.3.4, C1) · ADR-003, ADR-013, ADR-014

## Contexto
Al ejecutar por primera vez el pipeline completo sobre Davronov con todas las variables disponibles (salvo `Score_*`, `Sex`, `Age`, `Marital` y la fecha de nacimiento), el modelo base obtuvo una **exactitud balanceada de 0,9997**, imposible en un problema de crédito real. El análisis de cada variable por separado mostró dos fugas de la etiqueta:

| Variable | AUC univariado frente a `label` | Evidencia |
|---|---|---|
| `Field` | 0,992 | `Field = 0` concentra 656 de los 670 impagos (94 % de impago en esa categoría, frente a menos del 2 % en las demás) |
| `Changed_phone_number` | 0,986 | `Changed_phone_number = 0` → `label = 1` en 7 808 de 7 808 registros |

Lo más probable es que sean información posterior al resultado (un código de "sin dato" que solo tienen los que incumplen, o un cambio de teléfono asociado a la cobranza). El proyecto antiguo no las usaba, por eso no se había detectado. Además, `Field` era el principal *proxy* de `Sex` y `Age_group` en el C2 (AUC 0,76 y 0,61).

El C1 solo verificaba las columnas con fuga **declaradas** (`Score_*`). Una fuga no declarada pasaba sin control.

## Opciones consideradas
1. **Declarar las dos columnas como fuga, sin cambiar el motor.** Resuelve Davronov, pero en otro *dataset* el problema volvería a pasar inadvertido.
2. **Agregar al C1 una regla genérica** que calcule, para cada variable del modelo, el AUC univariado frente a la etiqueta y bloquee si alguna supera un umbral. Además, declarar las columnas detectadas como fuga.

## Decisión
**Opción 2.** Nueva métrica del C1, `max_feature_target_auc`: el máximo AUC univariado de las variables frente a la etiqueta. Las variables categóricas o con pocos valores se codifican por la tasa de la etiqueta en cada categoría, y se toma max(AUC, 1 − AUC). La regla es `C1-LEAK: max_feature_target_auc le 0.95` (`block`), y el reporte lista las variables sospechosas.

Se verificó que la regla detecta ambas columnas **sin haberlas declarado**: el C1 bloqueó el pipeline con `Field` (0,9924) y `Changed_phone_number` (0,9859). Después, se agregaron a `leakage_columns` en `domains/davronov/dataset.yaml`, con la evidencia en un comentario.

## Consecuencias
- **Resultados de la etapa 1 sin las columnas con fuga:**
  - C1 aprueba (el AUC máximo de una variable es 0,706, de `INPS_yes_no`).
  - C2 aprueba (`Sex` 0,51; `Age_group` 0,54–0,55).
  - C3 aprueba el modelo base (exactitud balanceada 0,726) y la remediación no se activa.
- **El umbral de 0,95 no está calibrado:** en Davronov separa con margen las fugas (≥ 0,986) de las variables legítimas (≤ 0,71). Un umbral más bajo podría bloquear variables muy predictivas pero legítimas; conviene tratarlo como los umbrales del C2.
- **Cambios en la tesis:** Cap. 4 (C1: nueva regla y columnas con fuga de Davronov). En el Cap. 5 es un resultado reportable: el control detectó una fuga que la especificación manual no incluía.
- **Pendiente del autor:** confirmar la interpretación de `Field` y `Changed_phone_number`. El *dataset* no tiene diccionario de columnas.
