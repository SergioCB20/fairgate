# ADR-017: El C4 alerta solo con evidencia de incumplimiento (mejor extremo del intervalo)

- **Fecha:** 2026-10-03
- **Estado:** aceptada
- **Relacionado con:** Contrato C4 · ADR-008 (lo modifica para el C4) · ADR-010 · Cap. 2 (2.1.7) · Cap. 4 (Contrato C4, 4.5.5) · Cap. 5 (5.3) · escenario E0

## Contexto
ADR-008 decide todas las compuertas con el **peor extremo** del intervalo bootstrap al 95 %: una regla se cumple solo si todo el intervalo la cumple. ADR-010 ya advertía que en el C4 los lotes son más pequeños que el conjunto de prueba y que *"el intervalo puede cruzar el umbral y bloquear con frecuencia"*.

Al implementar el C4 (2026-10-03) se midió ese efecto en el escenario de control de Davronov: lotes formados por particiones aleatorias del conjunto de prueba, sin deriva por construcción. Se usaron 20 particiones distintas por tamaño de lote. Para estimar la detección, en cada lote se cambió a desfavorable el 30 % de las decisiones favorables del grupo `<25`, lo que da una SPD cercana a 0,26:

| Registros por lote | Peor extremo: FP / detección | Valor puntual: FP / detección | Mejor extremo: FP / detección |
|---|---|---|---|
| 1 742 (1 lote) | 0 % / 100 % | 0 % / 100 % | 0 % / 100 % |
| 871 (2 lotes) | 75 % / 100 % | 0 % / 100 % | 0 % / 78 % |
| 435 (4 lotes) | 100 % / 100 % | 9 % / 99 % | 0 % / 51 % |
| 217 (8 lotes) | 100 % / 100 % | 36 % / 94 % | 1 % / 27 % |

FP: proporción de lotes de control con alguna alerta de deriva del sesgo. Es una medición exploratoria hecha para tomar esta decisión, no un resultado del Objetivo 4. La causa es el tamaño del grupo `<25`: unas 33 personas por lote de 435 registros. Con un grupo tan pequeño, el extremo superior de la SPD supera 0,10 aunque la disparidad real sea casi nula.

## Opciones consideradas
1. **Peor extremo, como en ADR-008.** El C4 solo sería útil con lotes del tamaño del conjunto de prueba completo, es decir, un único lote en Davronov. Con lotes menores, cada lote dispararía un reentrenamiento.
2. **Valor puntual** (`decide_on: point`). Detecta casi todo, pero los falsos positivos crecen sin control al achicar el lote, y la decisión vuelve a depender del azar del muestreo, que es lo que ADR-008 quería evitar.
3. **Mejor extremo** (`decide_on: best_bound`): la regla falla solo si **todo** el intervalo incumple el umbral.

## Decisión
**Opción 3** (decisión del autor, 2026-10-03). Se invierte la carga de la prueba según el momento del ciclo de vida:

- **C3, antes de desplegar:** se exige evidencia de que el modelo **cumple** (peor extremo, ADR-008). Un modelo dudoso no se despliega.
- **C4, en la operación:** se exige evidencia de que el modelo **dejó de cumplir** (mejor extremo). Un lote dudoso no dispara un reentrenamiento.

Así, el C4 mantiene controlados los falsos positivos para cualquier tamaño de lote, y su capacidad de detección crece con el tamaño del lote. El esquema común admite ahora `decide_on: worst_bound | best_bound | point`. El C3 sigue con `worst_bound` y el C4 de Davronov declara `best_bound`.

## Consecuencias
- **Detección con lotes pequeños:** con 435 registros por lote, el C4 detecta solo la mitad de los lotes con una SPD cercana a 0,26. El tamaño del lote (`params.batches` en el C4) pasa a ser un parámetro del protocolo de O4: más lotes dan más observaciones en el tiempo, pero cada uno detecta menos. Los escenarios E1–E5 deben reportar la detección según el tamaño del lote.
- **Asimetría que hay que explicar en la defensa:** un mismo valor (por ejemplo, SPD = 0,12 con IC [0,04; 0,18]) bloquearía el despliegue en el C3, pero no alertaría en el C4. Es intencional: el costo de un error es distinto en cada punto. Una falsa alerta en producción reentrena y redespliega un modelo sano; un falso cumplimiento antes del despliegue pone en producción un modelo sesgado.
- **Pruebas múltiples:** con 6 reglas por lote (3 métricas × 2 atributos), la probabilidad de que alguna falle por azar sube. Con el mejor extremo, se mantuvo en 0–1 % en la medición anterior.
- **Cambios en la tesis:** Cap. 4 (Contrato C4 y 4.5.5, "Tamaño de los lotes y pruebas múltiples"), Cap. 2 (2.1.7, si presenta el peor extremo como regla general) y Cap. 5 (5.3).
- **ADR-008 y ADR-010** siguen vigentes, salvo la regla de decisión del C4.
