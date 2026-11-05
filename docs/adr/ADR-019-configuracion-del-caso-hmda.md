# ADR-019: Configuración del caso HMDA (escenario E6)

- **Fecha:** 2026-10-15
- **Estado:** aceptada (decidida por el agente a pedido del autor, "haz todos los pendientes"; **validar con el autor**)
- **Relacionado con:** ADR-003 (HMDA como secundario) · ADR-006 (C2) · ADR-015 (C1-LEAK) · Cap. 6 (Tabla 20, E6; 6.5) · Cap. 5 (5.5.4) · `Proyecto/fairgate/domains/hmda/`

## Contexto
ADR-003 dejó a HMDA como caso secundario para aportar deriva real (E6) y comprobar que el motor se configura solo con YAML, pero sin fijar el recorte: estado, años, variables, atributos y grupos. El Cap. 6 lo marcaba como pendiente por esa razón. La lista de prestamistas *fintech* que mencionaba ADR-003 no está verificada.

## Opciones consideradas
1. **Todo un estado grande o el país:** cientos de miles de solicitudes por año; el C2 y el *bootstrap* tardarían horas por repetición.
2. **Un estado pequeño, todos los prestamistas, dos años consecutivos:** tamaño comparable a varias veces Davronov; sin filtrar por *fintech* (no verificable).
3. **Filtrar por prestamistas *fintech*:** sin una lista verificable de LEI, sería inventar el recorte.

## Decisión
**Opción 2.**
- **Fuente:** API del Data Browser de la FFIEC (`states=DE`, `actions_taken=1,3`): Delaware, 2022 como referencia (desarrollo, C1 a C3) y 2023 como producción (C4, 4 lotes aleatorios; los datos públicos no traen la fecha de la decisión). Se descartan los registros de entidades exentas (`Exempt`, 603 en 2022). Quedan 40 972 solicitudes en 2022 (75,7 % aprobadas) y 29 140 en 2023. Descarga y preparación reproducibles: `python -m experiments preparar-hmda` (`experiments/hmda.py`). Los datos no se versionan.
- **Etiqueta:** 1 = aprobada (`action_taken` = 1), 0 = denegada (3). Es la decisión del prestamista, no el pago.
- **Atributos protegidos** (autodeclarados): `Sex` (Male frente a Female; desfavorecido declarado: Female), `Race` (White frente a Black; Black) y `Age_group` (65 años o más frente a menos de 65; el regulador publica la edad en rangos, y 62 años no es un corte disponible). Las solicitudes conjuntas y las categorías "No disponible" no pertenecen a ningún grupo.
- **Fuga de la etiqueta:** se declaran las variables posteriores a la decisión (tasa, *spread*, costos, motivo de denegación) y, tras la primera iteración, `purchaser_type` y `hoepa_status`. **El C1-LEAK no las detectó** (AUC univariado 0,823 y 0,943, bajo 0,95), aunque son deterministas para las aprobadas (`hoepa_status` 1 o 2 → aprobada en 27 467 de 27 467). Es el mismo patrón que `Score_point` en Davronov: el AUC no prueba la ausencia de fuga.
- **Exclusiones por el C2:** en la primera iteración, el porcentaje de población minoritaria del sector censal y el condado fueron las dos primeras variables de la filtración hacia `Race` (L = 0,82). Se excluyen, como `Marital` en Davronov: usarlas reproduciría el *redlining* geográfico.
- **Umbrales:** los de Davronov, congelados, salvo `C1-NULLS` = 0,10, porque el regulador no exige el LTV en todas las solicitudes denegadas (6 % de nulos); se imputa en la Zona 2 y el C2 evalúa la imputación. **Los umbrales del C2 no se recalibran para HMDA.** Contratos congelados el 2026-10-15 (`experiments/congelamiento-hmda.json`).

## Consecuencias
- **El C2 bloquea HMDA aun sin las variables geográficas:** las variables crediticias centrales (LTV, deuda/ingreso, ingreso) separan los grupos con L entre 0,62 (sexo) y 0,76 (edad), por encima del tope absoluto de 0,60. No se pueden excluir sin dejar el modelo sin información. El tope absoluto calibrado en Davronov no se transfiere a un dominio con variables financieras ricas; el contrato necesitaría un mecanismo para declarar variables justificadas por necesidad del negocio (como `justification` en los atributos protegidos), que queda como trabajo futuro. En el E6, como en E0 a E5, la repetición continúa sin detenerse para medir el C4.
- **Cambio en el motor:** la reponderación fallaba con registros sin grupo (solicitudes conjuntas); ahora forman su propio estrato (`fairgate/gates.py`, prueba `test_remediation_keeps_records_without_group`). Es el único cambio de código que exigió HMDA; el resto es YAML y la preparación de los datos, propia del caso.
- La tesis debe explicar que la etiqueta de HMDA es una decisión de aprobación (no un pago) y que el recorte es un estado y no una población *fintech*.

## Resultado de la evaluación (2026-10-15, 30 semillas; Cap. 6, 6.5.8)
- C1: 0/30 bloqueos. C2: 30/30 (L mediana: edad 0,76, raza 0,72, sexo 0,63).
- C3: bloquea 10/30 por la SPD de la raza (valor 0,066–0,111, mediana 0,097); advierte en 29/30. Remediado cumple en 10/10, exactitud balanceada 0,720 → 0,722.
- C4 sobre 2023: deriva de datos en 30/120 lotes (siempre el mismo lote; `loan_purpose` derivó en 90/120: los refinanciamientos bajaron del 31 % al 20 %); deriva del sesgo (SPD de la raza) en 17/120, siempre el mismo lote (SPD mediana 0,13). Control (lotes de 2022): 0/120 y 1/120.
