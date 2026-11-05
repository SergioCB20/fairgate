# ADR-007: Trazabilidad con MLflow → RDFLib sobre PROV-O/DQV/SHACL, sin InterpretME

- **Fecha:** 2026-09-25
- **Estado:** aceptada
- **Relacionado con:** Zona 4 · Cap. 2 (2.2.3) · Cap. 4 (4.4, Figura 8, Tablas 14 y 15) · R.E.2.3, R.E.3.3, R.E.4.3

## Contexto
El diseño original usaba InterpretME para semantizar los metadatos, una ontología OWL propia y GraphDB como almacén. El Anexo B ya identificaba como riesgo la incompatibilidad de versiones entre InterpretME, MLflow y AIF360, y la falta de experiencia en web semántica. Además, la ontología original usaba en sus ejemplos propiedades que no estaban definidas, y en la discusión mencionaba clases (`fno:*`) que no existían.

## Opciones consideradas
1. **Mantener InterpretME y GraphDB:** alto riesgo de integración, porque la herramienta está pensada para otros pipelines y exige un servidor.
2. **Ontología totalmente propia con RDFLib:** controlable, pero reinventa conceptos de linaje y calidad ya estandarizados.
3. **MLflow como fuente única, un exportador propio con RDFLib, reutilización de PROV-O (linaje) y DQV (mediciones) y validación con SHACL;** RDFLib u Oxigraph como almacén y GraphDB opcional.

## Decisión
Opción 3. Solo se definen las clases propias del dominio (`fair:FairnessContract`, `fair:Rule`, `fair:GateExecution`, `fair:FairnessMeasurement`, etc.) sobre PROV-O (Lebo et al., 2013) y DQV (Albertoni & Isaac, 2016). Formas SHACL (Knublauch & Kontokostas, 2017) garantizan que cada registro esté completo. Cinco preguntas de competencia (Noy & McGuinness, 2001) guían el diseño y sirven como prueba de R.E.4.3.

## Consecuencias
- Menos dependencias y menos riesgo; no hace falta un servidor.
- Las propiedades usadas en los ejemplos quedan definidas y validadas (se resuelve una inconsistencia del Cap. 4 original).
- Se pierde la integración "lista para usar" que ofrecía InterpretME; el exportador es código propio que hay que probar.
- Hay que actualizar la tesis donde InterpretME aparecía como herramienta propia (ya hecho en los Caps. 1, 2 y 4 y en el Anexo B). En el Cap. 3 sigue citándose como literatura, lo cual es correcto.
