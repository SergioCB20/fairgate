# ADR-020: `fairgate` público, sin datos y con licencia MIT

- **Fecha:** 2026-11-05
- **Estado:** aceptada (decisión del autor); reemplaza a ADR-009 en lo relativo a la visibilidad del repositorio `fairgate`
- **Relacionado con:** ADR-002, ADR-009, ADR-014 · R.E.3.1 · artículo IEEE (disponibilidad del código) · Cap. 5 (5.1)

## Contexto
1. **Por qué eran privados.** ADR-009 puso los repositorios en privado porque la licencia del dataset Davronov ("Data files © Original Authors") no permite redistribuirlo, y el repositorio antiguo tenía el CSV en su historial (ADR-002, ADR-014). La privacidad era la forma de no incumplir esa licencia.
2. **Qué cambió.** ADR-014 creó `fairgate` como repositorio nuevo, cuyo historial nació sin datos. El 2026-11-05 se verificó que ninguna confirmación (*commit*) de ninguna rama contiene archivos `.csv`, `.parquet` o `.zip`, ni bloques de más de 1 MB; `data/` está excluido salvo el descriptor `.dvc`, que solo guarda el *hash* del archivo; y no hay secretos ni rutas personales. El repositorio antiguo ya no figura en la cuenta del autor.
3. **Necesidad.** El artículo y la evaluación del informe afirman resultados que un tercero debe poder inspeccionar y reproducir. Con el repositorio privado, el jurado y los revisores no pueden revisar el código (consecuencia ya anotada en ADR-009).

## Opciones consideradas
1. **Mantener `fairgate` privado y dar acceso de lectura puntual.** Cumple la licencia, pero no permite la reproducibilidad abierta que pide la evaluación de calidad de la revisión sistemática (criterio de reproducibilidad).
2. **Hacerlo público sin datos, con licencia, README de reproducción y resultados publicados.** Cumple la licencia del dataset porque no lo redistribuye, y permite inspección.
3. **Publicar también los datos.** Incumple la licencia de Davronov.

## Decisión
Opción 2.
- `fairgate` es público, con licencia **MIT** (`LICENSE`). El código es del autor; los datos no se redistribuyen y siguen sus propias licencias.
- Los conjuntos de datos se obtienen de su fuente (Kaggle y la API de la FFIEC); el README documenta los pasos y el *hash* que permite verificar el lote.
- Los resultados de la evaluación se publican en dos niveles: los resúmenes `.md` de `experiments/resultados/` quedan versionados, y los registros por repetición (`.jsonl`, unos 44 MB, solo métricas agregadas y sin filas del dataset) se publican como activo del *release* `resultados-articulo`.
- El remoto DVC (DagsHub) sigue privado. El trabajo de CI que lo usa (`compuertas-davronov`) solo corre si existen los *secrets*, de modo que se omite en copias del repositorio.
- Los ADR se copian a `docs/adr/` del repositorio para que las referencias del código, de los contratos y del README se resuelvan. Los contratos YAML no se editan, porque sus *hashes* están congelados.

## Consecuencias
- Hay que mantener la regla de no versionar datos (`.gitignore` de `data/`). Antes de cada publicación conviene repetir la comprobación del historial.
- El informe todavía habla de "repositorios privados" en R.E.3.1, en su indicador y en el Cap. 5: hay que actualizar esos textos (el autor decide el texto).
- La rama `demo-bloqueo` y el PR #1 (borrador) quedan visibles; se limpian después de la exposición.
- Quien copie el repositorio no podrá ejecutar la compuerta con datos reales sin descargar el dataset; es una restricción deliberada de la licencia, no un defecto.
