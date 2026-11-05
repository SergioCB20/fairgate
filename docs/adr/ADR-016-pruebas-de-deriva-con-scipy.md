# ADR-016: Implementar con SciPy las pruebas de deriva de datos de Evidently

- **Fecha:** 2026-10-03
- **Estado:** aceptada
- **Relacionado con:** Contrato C4 (regla de deriva de datos) · Zona 3 ("Monitor de deriva de datos") · Cap. 1 (Tabla 5) · Cap. 4 (Zona 3, Figuras 4 y 7, Contrato C4) · Cap. 5 (5.3) · ADR-010

## Contexto
El diseño asigna la deriva de datos del C4 a Evidently: *"proporción de variables cuya distribución en $B_t$ difiere significativamente de la de entrenamiento, según las pruebas de Evidently"* (Cap. 4). Al implementar la etapa 3 (2026-10-03), Evidently 0.7.23 se instaló sin cambiar ninguna versión del archivo de bloqueo, pero **falló al importarse**. El error (`KeyError: ~TResult`) se produce en la maquinaria de genéricos de `typing` de Python, al cargar `evidently.legacy.ui.type_aliases`. El entorno usa Python 3.11.0, y el fallo parece un defecto de esa versión inicial ya corregido en parches posteriores. No se verificó con otra versión de Python. Además, Evidently agrega unas 30 dependencias (servidor web, plotly, nltk, statsmodels), cuando del paquete solo se usan las pruebas estadísticas.

## Opciones consideradas
1. **Actualizar Python e instalar Evidently.** Mantiene la herramienta nombrada en la tesis, pero obliga a regenerar el archivo de bloqueo y a repetir las etapas 1 y 2 para confirmar que los resultados no cambian, y suma dependencias que el prototipo no usa.
2. **Reimplementar con SciPy las pruebas que Evidently aplica por defecto.** No agrega dependencias (SciPy ya estaba en el archivo de bloqueo como dependencia de scikit-learn) y cada prueba queda explícita en el código y en el resultado. Hay que documentar que se sigue el criterio de Evidently sin usar la biblioteca.
3. **Elegir otra prueba propia** (por ejemplo, el PSI). Se aparta del diseño sin necesidad.

## Decisión
**Opción 2** (decisión del autor, 2026-10-03). `fairgate/monitoring.py` aplica, por cada variable del modelo, la misma prueba que Evidently elige por defecto:

| Referencia (entrenamiento) | Variable | Prueba | Deriva si |
|---|---|---|---|
| Más de 1 000 registros | Numérica con más de 5 valores | Distancia de Wasserstein normalizada por la desviación estándar de la referencia | ≥ 0,1 |
| Más de 1 000 registros | Categórica o con 5 valores o menos | Distancia de Jensen-Shannon entre las frecuencias | ≥ 0,1 |
| 1 000 registros o menos | Numérica con más de 5 valores | Kolmogorov-Smirnov | p < 0,05 |
| 1 000 registros o menos | Categórica o con 5 valores o menos | Chi-cuadrado | p < 0,05 |

La regla `drift_share` del C4 es la proporción de variables con deriva. El umbral de las distancias se declara en el contrato (`params.stattest_threshold`).

## Consecuencias
- **Cambios en la tesis:** en el Cap. 1 (Tabla 5), el Cap. 4 (Zona 3, Contrato C4) y el Cap. 5, "Evidently" pasa a ser el criterio de las pruebas, implementadas con SciPy. Las Figuras 4 y 7 rotulan el monitor como "Evidently" y deben ajustarse al redibujarlas.
- **Verificación contra el código de Evidently 0.7.23** (rueda descargada el 2026-10-03, sin instalar): la selección de pruebas (`legacy/calculations/stattests/registry.py`, `_get_default_stattest`), los umbrales por defecto (0,1 con `≥` para las distancias; p < 0,05 para KS y chi-cuadrado), la normalización de Wasserstein (`max(std(referencia), 0,001)`), las frecuencias sin relleno de ceros para Jensen-Shannon y las frecuencias esperadas del chi-cuadrado (conteos de la referencia × n_lote / n_referencia) coinciden con la implementación.
- **Única diferencia:** con una referencia de 1 000 registros o menos, Evidently usa una prueba Z de proporciones para las variables con solo 2 valores; aquí se usa chi-cuadrado. En Davronov no influye, porque la referencia tiene 6 965 registros.
- **Ruido con lotes pequeños:** la distancia de Wasserstein entre dos muestras de una misma distribución ronda 0,04–0,12 con lotes de 400 registros. En el escenario de control de Davronov, `INPS_mln_sum` superó 0,1 en un lote (0,141) sin que hubiera deriva. Esto refuerza que la deriva de datos sea solo `warn` (ADR-010) y que el umbral de 0,30 deba calibrarse.
- Si más adelante se actualiza Python, se puede volver a Evidently sin cambiar el contrato: la regla y su métrica son las mismas.

## Verificación de equivalencia (2026-10-14; Cap. 6, 6.2.6 y 6.5.6)
- Evidently 0.7.23 **sí se carga con Python 3.13** (entorno aparte creado con `uv`); con el Python 3.11.0 del prototipo sigue fallando. Se confirma que el problema es de esa versión de Python.
- Comparación sobre los lotes de calibración de E0 y E5 (3 semillas, 90 lotes × 7 variables = **630 pruebas**; `experiments/drift_export.py` y `experiments/evidently_compare.py`): **misma prueba seleccionada y misma decisión en las 630**, con una diferencia máxima entre estadísticos menor que 5·10⁻⁵ (redondeo).
- El umbral de 0,30 de la proporción de variables con deriva se calibró con las semillas reservadas y se confirmó (0 % de falsos positivos en los lotes de control de todos los tamaños; Cap. 6, 6.2.5).
- Consecuencia: la reimplementación queda validada empíricamente, no solo contra el código fuente. Volver a Evidently sigue siendo posible si se actualiza Python, sin cambiar el contrato.
