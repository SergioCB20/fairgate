# ADR-002: Comprometer el CSV en Git para que el CI funcione (workaround de DVC)

- **Fecha:** 2026-09-19 (commits `a4ba809` y `f3977fa` del proyecto); documentado el 2026-09-25
- **Estado:** reemplazada por ADR-009 en lo que respecta a la publicación del dataset
- **Relacionado con:** R.E.3.1 · Zona 1 (DVC) · CI en GitHub Actions · Cap. 5 (5.2)

## Contexto
El dataset se versiona con DVC (remotos en DagsHub y Google Drive). En los clones limpios que hace GitHub Actions, la recuperación de los datos con DVC 3.67.1 falló; según los mensajes de commit, se trata de un bug de descubrimiento de esa versión. Sin datos, el CI no podía ejecutar las QA Gates.

## Opciones consideradas
1. **Depurar DVC en el CI** (credenciales del remoto, versión distinta): requería tiempo y bloqueaba el avance.
2. **Comprometer el CSV directamente en Git** solo para el CI y mantener DVC en el flujo local.
3. **Generar un dataset sintético para el CI:** no valida el pipeline sobre los datos reales.

## Decisión
Se eligió la opción 2 como solución pragmática: el CSV quedó en el repositorio y DVC sigue usándose localmente.

## Consecuencias
- El CI pasó a verde con las QA Gates 1, 2 y 3.
- **Efecto no previsto:** con los repositorios públicos, el dataset quedó redistribuido pese a que su licencia ("Data files © Original Authors") no lo permite. ADR-009 corrige esto (repositorios privados).
- Queda pendiente fijar la versión de DVC y resolver la recuperación de datos en el CI (con el remoto privado), para volver a tener una sola fuente de verdad para los datos.
