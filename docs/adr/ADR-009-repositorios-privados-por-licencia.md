# ADR-009: Repositorios privados y ejecución "reproducible local y en CI"

- **Fecha:** 2026-09-25
- **Estado:** aceptada (reemplaza a ADR-002 en lo relativo a la publicación del dataset); en lo relativo a la visibilidad de `fairgate`, reemplazada por ADR-020 (2026-11-05)
- **Relacionado con:** R.E.3.1 · Cap. 4 (4.2.2, 4.5.5) · Cap. 5 (5.1) · Anexo B (viabilidad, riesgos)

## Contexto
1. **Licencia:** la licencia del dataset Davronov es "Data files © Original Authors" y no permite redistribuirlo. Los repositorios de GitHub y DagsHub del proyecto son **públicos** (confirmado por el autor) y el CSV está en el historial de Git (ADR-002).
2. **Contradicción entre texto e implementación:** la tesis afirmaba que "el 100% de los contenedores lógicos debían operar en un entorno local desconectado de internet", pero la implementación usa GitHub Actions (ejecutores en la nube) y remotos DVC en DagsHub y Google Drive. El Anexo B, por su parte, hablaba de "herramientas nativas de la nube".

## Opciones consideradas
1. **Mantener los repositorios públicos:** incumple la licencia del dataset.
2. **Ejecutar todo en local sin internet:** coherente con el texto original, pero descarta el CI y los remotos que ya funcionan.
3. **Repositorios privados y el principio "reproducible local y en CI":** el mismo `pytest` en la estación de trabajo y en GitHub Actions, con dependencias fijadas; la confidencialidad se logra tratando los datos (privacidad del repositorio y seudonimización del atributo protegido), no aislando la red.

## Decisión
Opción 3. Los repositorios de código (GitHub) y datos (DagsHub/DVC) se ponen en privado. El README documenta cómo descargar el dataset de Kaggle. La tesis ya se reescribió con el nuevo principio (Cap. 4, 4.2.2).

## Consecuencias
- Hacer privados los repositorios no borra copias ya clonadas. Si se quiere retirar el CSV del historial, hay que reescribirlo (`git filter-repo`), una acción destructiva que el autor debe ejecutar con respaldo previo.
- Los repositorios privados limitan que el jurado revise el código; si lo requiere, se puede dar acceso de lectura puntual.
- Hay que fijar las versiones de las dependencias (incluida DVC) para cumplir la reproducibilidad en ambos entornos.
