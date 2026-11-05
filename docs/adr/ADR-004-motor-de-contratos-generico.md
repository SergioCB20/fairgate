# ADR-004: Motor de contratos genérico con esquema declarativo común

- **Fecha:** 2026-09-25
- **Estado:** aceptada
- **Relacionado con:** Contratos C1–C4 · Cap. 4 (Tablas 11 y 12, 4.3.1) · R.E.2.2, R.E.3.1, R.E.3.2

## Contexto
La tesis (Tabla 12) describe un esquema común para los contratos (`contract_id`, `gate`, `stage`, `protected_attributes`, `rules`, `on_violation`, `tooling`). La implementación inicial, en cambio, tenía un YAML con estructura distinta para cada contrato y un test escrito a mano para cada uno. `on_violation` (block/warn) y `tooling` no existían, y agregar un atributo protegido o una métrica exigía escribir código nuevo.

## Opciones consideradas
1. **Mantener un contrato y un test por gate, cada uno con su estructura:** es simple al inicio, pero diverge de la tesis y no escala a varios atributos protegidos ni a C4.
2. **Usar un framework externo de validación de ML:** no cubre contratos de equidad con remediación ni el registro semántico que requiere la Zona 4.
3. **Construir un motor propio con un esquema común validado**, pruebas generadas automáticamente y resultados estructurados.

## Decisión
Opción 3. Cada contrato YAML sigue el esquema común (Tabla 12) y se valida (pydantic o JSON Schema) antes de ejecutarse. Pytest genera **una prueba por cada combinación de regla y atributo protegido**. Cada regla declara `severity: block | warn`. Todas las evaluaciones producen un registro `GateExecution` que va a MLflow.

## Consecuencias
- La Tabla 12 de la tesis pasa a ser verdadera y verificable en el código.
- Agregar un atributo (por ejemplo, `Age_group`) o un dataset (HMDA) solo requiere un YAML nuevo.
- Hay que implementar y probar el motor antes que los gates. Es trabajo adicional en R.E.3.1, pero reduce el de R.E.3.2.
- Los resultados estructurados son el insumo directo de la trazabilidad (ADR-008).
