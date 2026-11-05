# ADR-003: Davronov como dataset principal y HMDA como secundario

- **Fecha:** 2026-09-25
- **Estado:** aceptada
- **Relacionado con:** O4 · Cap. 4 (Tabla 13, 4.5.5) · Cap. 5 (5.1) · Anexo B (viabilidad de datos, riesgos)

## Contexto
El software necesita un dataset que: (a) sea de scoring crediticio en un contexto fintech; (b) tenga atributos protegidos reales; (c) contenga proxies plausibles para el C2; (d) tenga dimensión temporal para la deriva; (e) sea lo bastante grande para métricas estables; y (f) pueda usarse y versionarse legalmente. El dataset actual (Davronov, Kaggle) cumple (a), (b) y (c), pero su ficha oficial muestra **licencia "Data files © Original Authors"**, **sin diccionario de columnas** (no se sabe qué significan 1 y 2 en `Sex`), sin marcas temporales y con solo 670 casos de *default*. Su origen en una fintech de Asia Central lo afirma Giang Thi Thu et al. (2024), no la página del dataset. Detalle en `estado/implementacion-vs-tesis.md`, sección 6.

## Opciones consideradas
1. **Solo Davronov:** mantiene la narrativa fintech, pero la deriva sería únicamente simulada y la procedencia es débil.
2. **Home Credit Default Risk (Kaggle):** gran tamaño y prestamista de consumo, pero sus reglas **prohíben redistribuir** los datos, algo incompatible con DVC/Git.
3. **German / South German Credit:** datos de 1973–75 y, en la versión original, el sexo no puede recuperarse de la variable conjunta de estado civil y sexo (Fabris et al., 2022).
4. **Taiwan Credit Card Default:** banco, no fintech, y sin dimensión temporal útil.
5. **HMDA como principal:** pública, con atributos autodeclarados y datos anuales, pero cambia el relato a hipotecas en EE. UU. y la etiqueta es la decisión del prestamista.
6. **Davronov como principal y HMDA como secundario.**

## Decisión
Opción 6.
- **Davronov** sostiene los Contratos C1–C4 y los escenarios E0–E5.
- **HMDA** (un estado, dos años) aporta deriva real (escenario E6) y demuestra que el diseño no depende del dataset.

Se añade **`Age_group`** (<25 / ≥25) como segundo atributo protegido de Davronov: el grupo de menores de 25 es el 7,5 % (cumple el C1) y su brecha en la etiqueta real es de 9,0 puntos, frente a 2,9 por sexo. Un corte en 60 años no sirve, porque ese grupo es el 4,1 % y fallaría el C1. Para `Sex` se usan métricas simétricas.

## Consecuencias
- La tesis debe declarar la licencia, la falta de diccionario y el carácter simulado de la deriva en Davronov (Cap. 4, 4.5.5).
- HMDA exige documentar el recorte (estado, años y, si aplica, la lista de prestamistas fintech, que aún no está verificada) y explicar que su etiqueta es una decisión, no un pago.
- Se suma el archivo `data_test.csv` de Davronov (≈48 filas), con lo que el total coincide con las 8 755 filas que reporta la literatura.
