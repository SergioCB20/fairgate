# ADR-001: Excluir `Marital` de las variables del modelo por ser proxy de `Sex`

- **Fecha:** 2026-09-16 (commit `793ba3d` del proyecto); documentado el 2026-09-25
- **Estado:** aceptada
- **Relacionado con:** QA Gate 2 / Contrato C2 · Cap. 2 (2.1.2, discriminación por proxy) · Cap. 4 (4.3.2 D y 4.3.3) · escenario E2 de O4

## Contexto
En el dataset Davronov, el atributo protegido `Sex` (valores 1 y 2) se excluye como variable de entrada del modelo. Aun así, el C2 (información mutua condicional entre las variables transformadas y `Sex`, dado `label`) detectó filtración de información del atributo protegido. El cruce `Marital × Sex` sobre los 8 707 registros muestra que **6 de las 7 categorías de estado civil pertenecen en su totalidad a un solo grupo de `Sex`**: `Marital` permite reconstruir `Sex` casi sin error. Es el caso de *fairness through unawareness* fallida que describe la Sección 2.1.2.

## Opciones consideradas
1. **Mantener `Marital`:** aporta información predictiva, pero reintroduce `Sex` de forma indirecta y el C2 falla.
2. **Transformar `Marital`** (agrupar categorías para romper la asociación): exige conocer el significado de los códigos, que el dataset no documenta, y no garantiza eliminar la asociación.
3. **Excluir `Marital`** de las variables de entrada.

## Decisión
Excluir `Marital` del pipeline de variables (opción 3). La exclusión queda documentada en el código (`zona1_ingesta/transformers/pipeline.py`) y como hallazgo del C2 en la tesis. Además, `Marital` se reutiliza como **caso positivo conocido**: para calibrar los umbrales del C2 rediseñado (ADR-006) y en el escenario E2 de O4, donde se reintroduce a propósito para verificar que el gate lo detecta.

## Consecuencias
- Se pierde una variable potencialmente predictiva; el impacto en la exactitud debe reportarse en el Cap. 5.
- Es la primera evidencia empírica de que una compuerta sobre los transformadores detecta un sesgo que no se ve en los datos crudos. Refuerza el argumento del sesgo composicional (Biswas & Rajan, 2021).
- La tesis debe mencionar que la codificación de `Marital` y de `Sex` no está documentada (ver ADR-003).
