# ADR-013: Columnas de origen de los atributos protegidos y política de uso como variable

- **Fecha:** 2026-09-28
- **Estado:** aceptada (el autor delegó la elección entre las dos opciones, con el criterio de maximizar la generalidad del sistema)
- **Relacionado con:** Contratos C1 y C2 · esquema declarativo (Cap. 4, Tabla 12) · ADR-003, ADR-004, ADR-006

## Contexto
`Age_group` (<25 / ≥25) es el segundo atributo protegido de Davronov (ADR-003), pero se deriva de la columna `Age`, que el pipeline valida con Pandera y que puede entrar al modelo. Si `Age` es una variable del modelo:

- el clasificador auxiliar del C2 reconstruye `Age_group` con un AUC cercano a 1, por lo que el C2 (tope 0,60) **bloquearía en todas las ejecuciones**;
- la afirmación de la tesis "el atributo protegido nunca es variable de entrada" deja de ser cierta.

El problema es general. Muchos atributos protegidos se derivan de una columna de origen (edad → tramo de edad) o tienen columnas equivalentes en otros *datasets* (HMDA publica sexo, raza, etnia y edad). En algunos marcos legales está permitido usar ciertas variables relacionadas, como la edad bajo condiciones en la ECOA. Por eso la decisión no puede depender de Davronov.

## Opciones consideradas
1. **Excluir `Age` del modelo** (regla fija para Davronov). Es simple, pero está cableada al caso.
2. **Aplicar el C2 solo a `Sex`.** Deja sin control el atributo que tiene la mayor brecha real.
3. **Declarar en el contrato la columna de origen de cada atributo protegido y si puede usarse como variable.** El motor aplica la política de forma genérica en el C1 y en el C2.

## Decisión
**Opción 3.** Cada atributo protegido del esquema declara dos campos más:

- `source_columns`: columnas de las que se deriva o que lo codifican directamente (en Davronov, `Age` para `Age_group` y `Sex` para `Sex`).
- `use_as_feature` (por defecto `false`): si esas columnas pueden ser variables del modelo. Si se pone `true`, el contrato debe incluir una justificación (`justification`), que queda registrada en el linaje.

Reglas genéricas:
- **C1 (columnas prohibidas):** además de las columnas con fuga de la etiqueta, se prohíben el atributo protegido y sus `source_columns` como variables del modelo, salvo que `use_as_feature: true`.
- **C2 (filtración):** el indicador $L_j^{(k)}$ se calcula sobre las variables **sin** las columnas de origen autorizadas del atributo $j$. Así mide la filtración por *proxies* que va más allá de lo explícitamente permitido.

**Configuración de Davronov:** `use_as_feature: false` para ambos atributos. `Age` se excluye del modelo, lo que mantiene que ningún atributo protegido ni su columna de origen entra al modelo, y el C2 mide la filtración de `Sex` y `Age_group` a través del resto de las variables.

## Consecuencias
- El C2 de `Age_group` pasa a ser informativo: detecta si otras variables, como la antigüedad del historial crediticio, reconstruyen el tramo de edad.
- Excluir `Age` puede reducir la exactitud del modelo base. Debe medirse y reportarse en el Cap. 5.
- Para HMDA y otros rubros basta con declarar las columnas de origen en el YAML. No hay reglas específicas por *dataset* en el código.
- **Cambios en el código (pendientes):** agregar `source_columns`, `use_as_feature` y `justification` al esquema (pydantic), aplicar la política en el ingestor (C1) y en el evaluador de filtración (C2), y quitar `Age` de las variables del pipeline de Davronov.
- **Cambios en la tesis:** Cap. 4 (Tabla 12, YAML del C3, C1 y C2, discusión y limitaciones).
