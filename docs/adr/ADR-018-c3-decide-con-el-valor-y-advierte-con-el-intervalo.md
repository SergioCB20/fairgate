# ADR-018: El C3 bloquea con el valor y advierte con el intervalo (regla en tres estados)

- **Fecha:** 2026-10-14
- **Estado:** aceptada (decidida por el agente a pedido del autor, que delegó la resolución de los problemas de la calibración; **validar con el autor**)
- **Relacionado con:** Contrato C3 · ADR-008 (lo modifica para el C3) · ADR-017 · Cap. 2 (2.1.7) · Cap. 4 (Contrato C3) · Cap. 5 (5.3) · Cap. 6 (6.2.5) · `estado/o4-implementacion.md`

## Contexto
ADR-008 decide el C3 con el **peor extremo** del intervalo bootstrap al 95 %: el modelo debe demostrar que cumple incluso en el caso desfavorable. La calibración del O4 (2026-10-14, semillas reservadas 1000–1029, escenario de control E0 sin ninguna inyección) mostró que, con el tamaño del grupo pequeño de Davronov (~130 menores de 25 en la prueba), esa regla bloquea un modelo justo con frecuencia:

- La SPD de la edad **nunca** superó 0,10 (mediana 0,034; máximo 0,084).
- El peor extremo tuvo una mediana de 0,099 (rango 0,066–0,154): el C3 bloqueó en **14 de 30** semillas.
- La remediación no lo corrigió en 13 de los 14: no había sesgo que corregir, solo ruido de muestreo.

La semilla de desarrollo (42), con la que se escribió el Cap. 5, cayó en el lado favorable.

Se compararon alternativas sobre las mismas 30 semillas (falsos positivos en E0; detección en E4 con ruta y 10 % de etiquetas invertidas, un sesgo moderado):

| Regla | Falsos positivos (E0) | Detección (E4 con ruta, 10 %) |
|---|---|---|
| IC 95 %, peor extremo (ADR-008) | 14/30 | 27/30 |
| IC 90 %, peor extremo | 11/30 | 23/30 |
| IC 90 %, peor extremo, prueba del 30 % | 4/30 | 20/30 |
| IC 95 %, peor extremo, prueba del 30 % | 7/30 | 23/30 |
| Valor puntual | 0/30 | 6/30 |

## Opciones consideradas
1. **Mantener el peor extremo** y reportar los falsos positivos. Coherente con ADR-008, pero una compuerta de CI que falla la mitad de las veces sin causa no es utilizable: el equipo aprendería a ignorarla.
2. **Intervalo al 90 % (convención de las pruebas de equivalencia) o un conjunto de prueba más grande.** Reducen los falsos positivos, pero ninguna variante baja del 13 %, y agrandar la prueba cambia la partición de todo el pipeline.
3. **Valor puntual** como única regla. Sin falsos positivos, pero descarta la información de la incertidumbre que motivó ADR-008.
4. **Tres estados:** bloquear con el valor puntual (hay evidencia de incumplimiento en la muestra) y advertir (`warn`) cuando el valor cumple pero el peor extremo no ("la muestra no permite demostrar el cumplimiento").

## Decisión
**Opción 4.** El C3 decide sus reglas `block` (`C3-SPD`, `C3-EOD`, `C3-DI`) con el valor puntual (`statistics.decide_on: point`) y agrega una regla `warn` por métrica con el peor extremo (`C3-SPD-IC`, `C3-EOD-IC`, `C3-DI-IC`; `decide_on: worst_bound` por regla). El motor admite ahora una regla de decisión por regla, que reemplaza a la del contrato. Contrato C3 v4.0.

La advertencia no detiene el pipeline, pero queda en el linaje, en el grafo (como cualquier medición) y en el reporte de cumplimiento, de modo que el auditor ve cuándo el cumplimiento no está demostrado estadísticamente.

## Consecuencias
- **La familia de decisiones queda así:** el C3 bloquea con el valor y advierte con el intervalo; el C4 alerta solo con el mejor extremo (ADR-017). El principio de la tesis se matiza: la regla de decisión depende de la etapa **y del tamaño del grupo pequeño**. Con grupos de ~130 personas, un umbral de 0,10 no puede *demostrarse* con un IC 95 %; puede verificarse que no se incumpla.
- **Costo:** se pierde sensibilidad ante sesgos moderados, por debajo del umbral pero con intervalos que lo cruzan (detección 6/30 frente a 27/30 en E4 con ruta al 10 %). Esos casos quedan como advertencias, no como bloqueos. La evaluación del O4 lo cuantifica.
- **Cambios en la tesis:** Cap. 2 (2.1.7, la decisión con el peor extremo), Cap. 4 (Contrato C3 y su YAML), Cap. 5 (5.3: "el C3 aprueba el modelo base" vale para la semilla 42; con el peor extremo habría bloqueado en ~47 % de las particiones) y Cap. 6 (6.2.5: la calibración motivó este cambio; se hizo antes de congelar).
- **Alternativa a futuro:** exigir en el C1 un tamaño mínimo absoluto del grupo pequeño en la prueba, compatible con el umbral, en lugar de solo la proporción del 5 %.
