# Resultados del E6 (HMDA): logistic_regression

Repeticiones: 30.

## Desarrollo (año de referencia)

| Compuerta | Bloquea [IC 95 %] | Reglas que bloquean (repeticiones) |
|---|---|---|
| C1 | 0/30 (0%) [0.00; 0.11] | — |
| C2 | 30/30 (100%) [0.89; 1.00] | C2-AUC[Sex] (30), C2-AUC[Race] (30), C2-AUC[Age_group] (30) |
| C3 | 10/30 (33%) [0.19; 0.51] | C3-SPD[Race] (10) |
| C3 remediado | 0/10 (0%) [0.00; 0.28] | — |

Filtración del C2 en la entrada (mediana) y variables que más la explican:

| Regla | L | Tres primeras variables (más frecuente) |
|---|---|---|
| C2-AUC[Age_group] | 0.759 | loan_to_value_ratio · income · loan_purpose |
| C2-AUC[Race] | 0.722 | loan_to_value_ratio · debt_to_income_ratio · loan_type |
| C2-AUC[Sex] | 0.627 | income · property_value · loan_type |

Métricas del C3 (mediana del valor; modelo base y remediado):

| Regla | Base | Remediado |
|---|---|---|
| C3-DI[Age_group] | 0.957 | 0.940 |
| C3-DI[Race] | 0.858 | 0.881 |
| C3-DI[Sex] | 0.992 | 0.997 |
| C3-EOD[Age_group] | 0.031 | 0.040 |
| C3-EOD[Race] | 0.047 | 0.032 |
| C3-EOD[Sex] | 0.010 | 0.009 |
| C3-SPD[Age_group] | 0.029 | 0.041 |
| C3-SPD[Race] | 0.097 | 0.081 |
| C3-SPD[Sex] | 0.007 | 0.009 |

Exactitud balanceada: base 0.720; remediado 0.722.

## Operación: lotes del año siguiente (deriva real)

Lotes: 120 (mediana de 7285 registros).

| Indicador | Valor |
|---|---|
| Lotes con alerta de deriva de datos (warn) | 30/120 (25%) [0.18; 0.33] |
| Proporción de variables con deriva (mediana) | 0.077 |
| Lotes con alerta de deriva del sesgo (Trigger CT) | 17/120 (14%) [0.09; 0.22] |
| Variables con deriva (lotes) | loan_purpose (90), income (60), loan_amount (30), property_value (30) |
| Reglas que alertan (lotes) | C4-SPD[Race] (17) |

Métricas por lote (mediana):

| Regla | Mediana |
|---|---|
| C4-DI[Age_group] | 0.936 |
| C4-DI[Race] | 0.864 |
| C4-DI[Sex] | 0.977 |
| C4-EOD[Age_group] | 0.041 |
| C4-EOD[Race] | 0.033 |
| C4-EOD[Sex] | 0.006 |
| C4-SPD[Age_group] | 0.042 |
| C4-SPD[Race] | 0.089 |
| C4-SPD[Sex] | 0.014 |

## Control: lotes de la prueba del año de referencia

Lotes: 120 (mediana de 2049 registros).

| Indicador | Valor |
|---|---|
| Lotes con alerta de deriva de datos (warn) | 0/120 (0%) [0.00; 0.03] |
| Proporción de variables con deriva (mediana) | 0.000 |
| Lotes con alerta de deriva del sesgo (Trigger CT) | 1/120 (1%) [0.00; 0.05] |
| Variables con deriva (lotes) | loan_amount (3), property_value (2), income (1) |
| Reglas que alertan (lotes) | C4-SPD[Race] (1) |

Métricas por lote (mediana):

| Regla | Mediana |
|---|---|
| C4-DI[Age_group] | 0.952 |
| C4-DI[Race] | 0.871 |
| C4-DI[Sex] | 0.993 |
| C4-EOD[Age_group] | 0.037 |
| C4-EOD[Race] | 0.042 |
| C4-EOD[Sex] | 0.020 |
| C4-SPD[Age_group] | 0.034 |
| C4-SPD[Race] | 0.088 |
| C4-SPD[Sex] | 0.016 |

Duración por repetición (mediana): 44.8 s; C2: 24.8 s.
