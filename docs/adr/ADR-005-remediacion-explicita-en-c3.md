# ADR-005: Remediación explícita en el Contrato C3 (ThresholdOptimizer)

- **Fecha:** 2026-09-25 (formaliza lo implementado en el commit `793ba3d` y siguientes)
- **Estado:** aceptada; **la técnica (`ThresholdOptimizer`) fue reemplazada por la reponderación en ADR-012** (2026-09-28). Se mantienen la remediación explícita dentro del gate, el DI direccional o simétrico y la guardia de exactitud.
- **Relacionado con:** QA Gate 3 / Contrato C3 · Cap. 2 (2.1.6) · Cap. 4 (Figura 6, 4.3.4) · R.E.3.2

## Contexto
El modelo base (regresión logística con pesos de clase balanceados) **incumple el C3** en Davronov: según el README del proyecto, amplifica la disparidad del label real (≈2,8 pp) hasta ≈18 pp en las predicciones. En la implementación inicial, el CI marcaba ese paso con `continue-on-error: true` y luego evaluaba un modelo mitigado con `ThresholdOptimizer` (Fairlearn, *equalized odds*). La tesis, en cambio, decía que ante un incumplimiento se interrumpe el despliegue, sin mencionar ninguna mitigación. Además, el DI se calculaba como mínimo/máximo con un límite superior de 1,25 que nunca podía activarse.

## Opciones consideradas
1. **Solo bloquear** y dejar la mitigación como un paso manual documentado: más simple, pero el pipeline nunca aprobaría un modelo en Davronov sin intervención.
2. **Mantener `continue-on-error`:** oculta el fallo del modelo base en el CI.
3. **Remediación explícita dentro del gate:** evaluar la base; si falla, aplicar la mitigación declarada en el contrato y reevaluar; bloquear solo si el mitigado también falla. Se registran ambos modelos.

## Decisión
Opción 3 (aprobada por el autor). La técnica se declara en el contrato (`remediation: threshold_optimizer, equalized_odds`), que corresponde al post-procesamiento de Hardt et al. (2016), implementado en Fairlearn (Weerts et al., 2023). El atributo protegido se usa solo en ese post-procesamiento, nunca como variable de entrada. El DI se calcula de forma **direccional** si se conoce el grupo no privilegiado (`Age_group`: <25) y **simétrica** si no (`Sex`); se elimina el límite de 1,25. Se agrega una guardia `warn` sobre la pérdida de exactitud balanceada (≤ 0,05).

## Consecuencias
- El CI refleja el flujo real sin `continue-on-error`.
- El registro de los dos modelos documenta el trade-off precisión-equidad (Menon & Williamson, 2018) y da evidencia para la discusión de multiplicidad (2.1.6).
- `ThresholdOptimizer` produce predicciones que dependen del grupo; la tesis debe discutir su pertinencia legal en crédito como limitación, porque la decisión final usa umbrales distintos por grupo.
