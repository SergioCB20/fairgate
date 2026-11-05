# ADR-012: Remediación del C3 sin usar el atributo protegido en la inferencia (reponderación)

- **Fecha:** 2026-09-28
- **Estado:** aceptada (decisión del autor). Reemplaza la técnica de ADR-005; el resto de ADR-005 (remediación explícita dentro del gate, DI direccional o simétrico y guardia de exactitud) se mantiene.
- **Relacionado con:** QA Gate 3 / Contrato C3 · Zona 2 y Zona 3 · Cap. 1 (herramientas: Fairlearn) · Cap. 2 (2.1.3) · Cap. 4 (4.2.1, 4.3.1, 4.3.4, 4.4, 4.5) · ADR-005, ADR-011, ADR-013

## Contexto
ADR-005 adoptó `ThresholdOptimizer` de Fairlearn (post-procesamiento de Hardt et al., 2016, con restricción de *equalized odds*). La documentación oficial de Fairlearn advierte tres problemas para el crédito:

1. **Necesita el atributo protegido en la inferencia:** *"ThresholdOptimizer requires the sensitive features to be available at deployment time (i.e., for the `predict` method)"*. Esto contradice la Zona 3, que guarda el atributo "exclusivamente para el cálculo de métricas de equidad".
2. **Trato dispar:** *"Due to the separate thresholding rules per sensitive feature value, one might argue that this constitutes disparate treatment under US anti-discrimination law or direct discrimination under EU non-discrimination law"*. La ECOA prohíbe considerar el sexo en la decisión de crédito.
3. **Predicciones aleatorias:** *"ThresholdOptimizer uses one of the thresholds at random"*. Dos solicitantes idénticos pueden recibir decisiones distintas, y las razones de rechazo de SHAP explican el *score*, no el umbral ni el sorteo.

ADR-005 ya pedía discutir esto como limitación, pero el autor prefiere cambiar la técnica. Requisito adicional del autor: el sistema debe ser configurable para otros *datasets* del mismo rubro y para otros rubros.

## Opciones consideradas
1. **Mantener `ThresholdOptimizer` y declarar la limitación.** No toca el código, pero deja un diseño que usa el atributo protegido en cada decisión de crédito.
2. **Reducciones de Fairlearn (`ExponentiatedGradient`, en el entrenamiento).** Usa el atributo solo al entrenar, pero el clasificador resultante también es aleatorio (mezcla de modelos).
3. **Reponderación en el preprocesamiento** (Kamiran & Calders, 2012, sección 5.2). A cada combinación de grupo y clase se le asigna un peso $W(g, y) = \frac{P(Z = g)\,P(Y = y)}{P(Z = g,\ Y = y)}$, de modo que, en los datos ponderados, la etiqueta es independiente del grupo. El modelo se reentrena con esos pesos. El atributo se usa solo en el entrenamiento, el modelo resultante es determinista y funciona con cualquier estimador que acepte pesos por muestra.

## Decisión
**Opción 3 como técnica por defecto**, dentro de un **catálogo de técnicas de remediación** declaradas en el contrato:

- El contrato declara `remediation: {method: reweighing, allow_protected_at_inference: false}`.
- El motor de contratos **rechaza** cualquier técnica que necesite el atributo protegido en la inferencia, salvo que el contrato declare `allow_protected_at_inference: true` (por ejemplo, en un dominio donde sea legalmente admisible). Por defecto es `false`.
- Con varios atributos protegidos (en Davronov, `Sex` y `Age_group`), los pesos se calculan sobre las combinaciones de grupos. Es una extensión propia del diseño, porque Kamiran y Calders (2012) tratan un solo atributo binario. Una combinación con muy pocos registros produce pesos extremos; el motor la reporta.
- Tras reentrenar con pesos, la QA Gate 3 se reevalúa con las mismas reglas (SPD, EOD, DI). Si el modelo remediado tampoco cumple, se bloquea el despliegue, igual que en ADR-005.

## Consecuencias
- **Coherencia:** la Zona 3 vuelve a ser coherente, porque el atributo protegido solo se usa para medir. El *scorer* no lo necesita.
- **Explicabilidad:** las razones de rechazo (SHAP sobre el modelo remediado) explican la decisión real, porque el umbral es único y la decisión es determinista.
- **Eficacia no garantizada:** la reponderación busca la independencia entre la etiqueta y el grupo en los datos de entrenamiento, lo que actúa sobre todo sobre SPD y DI. No garantiza la EOD. Si en Davronov el modelo reponderado no cumple el C3, el resultado correcto es el bloqueo, y el contrato permite probar otra técnica del catálogo sin cambiar código. **Debe medirse en el Cap. 5.**
- **Cambios en el código (pendientes):** implementar la reponderación en el módulo de remediación (con `sample_weight` de scikit-learn, sin depender de AIF360) y la validación de `allow_protected_at_inference` en el esquema. Los resultados del README (18 pp → cumple tras `ThresholdOptimizer`) dejan de describir el diseño vigente.
- **Cambios en la tesis:** Cap. 1 (herramienta Fairlearn), Cap. 2 (2.1.3: *equalized odds* ya no es restricción de la remediación), Cap. 4 (Zona 2, esquema, C3, ontología, discusión) y ADR-011.
- **Referencia nueva:** Kamiran, F., & Calders, T. (2012). *Knowledge and Information Systems*, 33(1), 1–33 (PDF de acceso abierto en `bibliografia/docs/`).
