# ADR-006: Evaluar el Contrato C2 por transformador con el AUC de un clasificador auxiliar

- **Fecha:** 2026-09-25
- **Estado:** aceptada (los umbrales deben calibrarse)
- **Relacionado con:** QA Gate 2 / Contrato C2 · Cap. 4 (Figura 5, 4.3.4) · R.E.4.2 (precisión de localización) · escenarios E2 y E3

## Contexto
La tesis define el C2 como I(X_trans; Z | Y) < 0,10 y afirma que compara la distribución antes y después de la transformación para aislar al transformador responsable. La implementación inicial calcula la información mutua de **cada variable por separado** (k-NN), toma el máximo y lo evalúa **solo sobre la salida final** del pipeline. No compara antes y después ni identifica el paso responsable, que es justo la capacidad de "localización" que O4 promete medir.

## Opciones consideradas
1. **Mantener la MI por variable sobre la salida final:** simple, pero no localiza y no capta combinaciones de variables.
2. **MI condicional conjunta** sobre todas las variables: difícil de estimar de forma estable en alta dimensión.
3. **AUC de un clasificador auxiliar** que predice Z a partir de X, estratificado por Y, calculado **después de cada paso** de preprocesamiento, con un tope absoluto y un incremento máximo por paso.

## Decisión
Opción 3, conservando la MI como métrica secundaria. Reglas: $L^{(k)} \le 0{,}60$ y $L^{(k)} - L^{(k-1)} \le 0{,}02$. El reporte indica el paso $k$ y las variables más influyentes en el clasificador auxiliar. Se prefiere el AUC porque es interpretable (0,5 = azar), capta combinaciones de variables y permite la localización.

## Consecuencias
- El C2 hace medible la "precisión de localización" de R.E.4.2.
- Los umbrales 0,60 y 0,02 **no provienen de una norma**. Deben calibrarse con `Marital` (caso positivo, ADR-001) y el pipeline sin `Marital` (caso negativo), y el resultado se documenta en el Cap. 5.
- El pipeline de preprocesamiento debe poder ejecutarse paso a paso, lo que obliga a cambiar la implementación del `ColumnTransformer` actual.
