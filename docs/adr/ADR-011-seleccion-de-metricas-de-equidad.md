# ADR-011: Selección de las métricas de equidad (SPD, EOD y DI como reglas; métricas individuales fuera de las compuertas)

- **Fecha:** 2026-09-27
- **Estado:** aceptada (formaliza a posteriori una elección que ya estaba en los contratos C3 y C4)
- **Relacionado con:** Contratos C3 y C4 · Cap. 2 (2.1.3, 2.1.4) · Cap. 4 (4.3, Contrato C3) · ADR-005, ADR-008, ADR-010

## Contexto
El Cap. 2 presenta dos familias de métricas: de grupo (SPD, EOD, DI) en 2.1.3 e individuales (Consistencia, CDS, LUF) en 2.1.4. Los contratos C3 y C4 usan solo las de grupo, y las individuales no aparecen en ningún contrato, compuerta ni escenario. La tesis no explicaba por qué se eligieron unas y se dejaron fuera las otras.

Para tener evidencia, se revisaron los PDF locales de los estudios del estado del arte citados en la tesis. **No es la lista oficial de los 22 estudios primarios**, que no está en el repositorio. Este fue el resultado:

| Estudio | Métricas de grupo | Métricas individuales |
|---|---|---|
| Biswas & Rajan (2021) | SPD, EOD, AOD, ERD | — |
| Nguyen (2024) | DI, SPD, EOD, AOD; el *Fairness Contract* se evalúa con SPD y EOD | — |
| Ji et al. (2023) | DI, SPD, AOD | Consistencia, índice de Theil, CDS |
| Ghai et al. (2022) | SPD y diferencias de FPR, FNR, FDR, FOR, exactitud y F1 | Consistencia, índice de Theil |
| Zhu et al. (2025) | SPD, igualdad de oportunidades | — |
| Nigenda et al. (2022) | Paridad estadística, igualdad de oportunidades (entre otras) | — |
| Avuthu (2021) | DI e igualdad de oportunidades (menciona la paridad demográfica) | — |
| Reda et al. (2025) | Paridad demográfica, con umbral de 0,1 | — |
| Black & Fredrikson (2021) | — | LUF |

Grafberger et al. (2022, 2023), Schelter et al. (2023), Vasquez et al., Russo et al. (2024) y Russo & Vidal (2025) no usan métricas concretas de equidad de este tipo. Frecuencia entre los 9 estudios que sí las usan: **SPD o paridad, 8; EOD o igualdad de oportunidades, 5; DI, 3; AOD o *equalized odds*, 3**; Consistencia, 2; Theil, 2; CDS, 1; LUF, 1.

**Actualización 2026-09-28 (lista oficial):** se obtuvo el formulario de extracción del Anexo A (copia en `bibliografia/anexo-A-formulario-extraccion-2026-09-28.csv`), con la lista oficial de estudios primarios. Tras excluir D19 por el criterio CE-5, quedan 21. El conteo se hizo sobre la columna "Métricas de Equidad y Trade-offs" de la hoja; para D08 (Ji et al.) se usaron las métricas verificadas en el PDF, porque la hoja no las lista. De los 21 estudios, 13 usan métricas concretas de equidad. Frecuencia entre esos 13: **SPD o paridad, 12; EOD o igualdad de oportunidades, 11; DI, 3; AOD o *equalized odds*, 3**; Consistencia, 2; Theil, 2; CDS, 1; LUF, 1. Los 8 restantes (D03, D05, D09, D12, D17, D18, D20 y D22) son herramientas agnósticas a la métrica, trabajos de documentación o marcos conceptuales. El orden relativo no cambia: SPD y EOD siguen siendo las más usadas y el DI sigue siendo poco frecuente, por lo que su inclusión se sostiene sobre todo en el criterio legal (criterio 1), no en la frecuencia.

## Opciones consideradas
1. **Solo métricas de grupo (SPD, EOD, DI) como reglas de compuerta.** Son simples, tienen respaldo legal y se usan mucho. No detectan un trato distinto entre individuos parecidos.
2. **Métricas de grupo más Consistencia como regla `warn`.** Aporta la mirada individual, pero su resultado depende de la escala y de la métrica de distancia entre variables, y no tiene un umbral de referencia.
3. **Conjunto amplio (SPD, EOD, DI, AOD, Consistencia, CDS, LUF).** Es completo, pero multiplica las pruebas múltiples, los falsos positivos en E0 y el costo, y algunas métricas no tienen sentido en este diseño (ver abajo).

## Decisión
Se elige la **opción 1**, con estos criterios:

1. **Respaldo legal y regulatorio.** El DI permite aplicar directamente la regla de los cuatro quintos (Uniform Guidelines, 1978), usada en la doctrina de impacto dispar en crédito (Bartlett et al., 2022).
2. **Sentido en el dominio del crédito.** La EOD es la igualdad de oportunidades de Hardt et al. (2016), que la plantean con el ejemplo del crédito: *"people who pay back their loan, have an equal opportunity of getting the loan in the first place"*. El error que más perjudica al solicitante es que se le niegue un crédito que habría pagado.
3. **Complementariedad.** SPD y DI miden la independencia entre la decisión y el grupo, sin considerar la etiqueta. La EOD mide si el error es igual entre grupos, condicionando en Y = 1. Hardt et al. (2016) muestran que la paridad demográfica por sí sola puede cumplirse aceptando a solicitantes no calificados en un grupo, así que no basta. SPD y DI se basan en la misma tasa (Biswas & Rajan, 2021), pero se usan en dos escalas: la diferencia, con el umbral técnico de 0,10 que Reda et al. (2025) describen como práctica común, y el cociente, con el criterio legal de 0,80.
4. **Frecuencia en la literatura revisada.** SPD y EOD son las dos métricas más usadas y son las que usa Nguyen (2024) en su *Fairness Contract*, que es el antecedente directo de los contratos de la tesis.
5. **Viabilidad operativa.** Se calculan con Fairlearn en una sola pasada por lote, con intervalos bootstrap (ADR-008), y tienen forma simétrica cuando no se conoce el grupo no privilegiado (Weerts et al., 2023).

**Métricas descartadas como reglas de compuerta:**
- **AOD (*equalized odds*):** agrega la paridad de falsos positivos, es decir, de aprobar a malos pagadores. Ese error afecta sobre todo al prestamista, y exigirla restringe más la exactitud; Hardt et al. (2016) presentan la igualdad de oportunidades como una versión relajada que en general conserva más utilidad. *Equalized odds* se usaba como restricción de la remediación en el C3 (ADR-005); desde ADR-012 la remediación es por reponderación y ya no usa esa restricción.
- **CDS:** mide si cambia la predicción al alterar el atributo protegido. En este diseño **el atributo protegido no es una entrada del modelo**, así que la CDS sería 0 por construcción y no informaría nada. El riesgo que sí importa, que el modelo reconstruya el atributo mediante proxies, lo mide el C2 (ADR-006).
- **LUF:** requiere reentrenar el modelo una vez por cada registro excluido, unas 7 000 veces en Davronov, y eso se multiplica por el bootstrap. Es inviable dentro de una compuerta de CI.
- **Consistencia:** depende de la escala y de la distancia elegida en el espacio de variables, y no hay un umbral normativo ni de práctica común. En la literatura revisada aparece solo como métrica de análisis (Ghai et al., 2022; Ji et al., 2023).

## Consecuencias
- La sección 2.1.4 se mantiene como marco conceptual, con un párrafo que explica por qué las métricas individuales no se usan como reglas. En 2.1.3 se agrega un párrafo con los criterios de selección.
- **Limitación asumida:** las compuertas no detectan un trato distinto entre individuos parecidos que no se refleje en las tasas por grupo. Debe declararse en las limitaciones.
- Se corrigieron citas del Cap. 2 que no respaldaban lo afirmado: Russo et al. (2024) y Russo & Vidal (2025) no definen SPD, EOD ni DI; Mehrabi et al. (2021) no define la Consistencia ni la LUF; Biswas & Rajan (2021) no trata la LUF. También se corrigió en el Cap. 4 la frase "métricas de equidad de grupo de Hardt et al. (2016)", porque Hardt propone la EOD, pero no la SPD ni el DI.
- Si en el futuro se agrega una métrica individual, el esquema de contratos la admite sin cambios (ADR-004), pero el motor solo ejecuta las métricas de su catálogo (`GATE_METRICS` en `fairgate/gates.py`; `check_contract` rechaza las demás). Por eso hay que implementar su cálculo y registrarla en el catálogo de la compuerta; la orquestación, el linaje y el grafo no cambian. La Consistencia como regla `warn` en el C3 es la candidata más barata. *(Precisión agregada el 2026-10-25.)*
- ~~**Pendiente del autor:** contrastar la tabla de frecuencias con la lista oficial de los 22 estudios primarios~~ Resuelto el 2026-09-28 con la lista oficial (21 estudios tras excluir D19): el criterio 4 se mantiene (ver la actualización en Contexto).
