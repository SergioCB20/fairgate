# ADR-008: Decidir las compuertas con intervalos de confianza bootstrap

- **Fecha:** 2026-09-25
- **Estado:** aceptada
- **Relacionado con:** Contratos C3 y C4 (y C2 si aplica) · Cap. 2 (2.1.7) · Cap. 4 (4.3.1, 4.3.4) · escenario E0 (falsos positivos)

## Contexto
Davronov tiene 670 casos de *default* y un grupo `Age_group < 25` de 650 personas. Con una partición 80/20, el conjunto de prueba tiene unas 1 740 filas, de modo que las métricas por grupo (en especial EOD y DI) varían bastante según la semilla. Una compuerta que compara el valor puntual con el umbral puede aprobar o fallar por azar, lo que además inflaría la tasa de falsos positivos del escenario de control (E0).

## Opciones consideradas
1. **Valor puntual con una semilla fija:** reproducible, pero la decisión depende de esa partición concreta.
2. **Validación cruzada y promedio:** reduce la varianza, pero no cuantifica la incertidumbre ni indica cuán cerca está la métrica del umbral.
3. **Intervalo de confianza bootstrap** (500 remuestreos, 95 %) y decisión con el **extremo más desfavorable** respecto del umbral.

## Decisión
Opción 3 (Efron & Tibshirani, 1993). Cada `FairnessMeasurement` se registra con su valor, `ciLow` y `ciHigh`, y la regla se evalúa con el peor extremo (`decide_on: worst_bound`).

## Consecuencias
- Decisiones más conservadoras y defendibles; en particular, la tasa de falsos positivos de E0 debería bajar y hay que medirla.
- Mayor costo computacional (500 re-evaluaciones por métrica). Se mitiga con un modelo lineal y ajustando el número de remuestreos.
- Un modelo cuyo valor puntual cumple el umbral puede ser bloqueado si su intervalo lo cruza. Este comportamiento es intencional y debe explicarse en la tesis.
