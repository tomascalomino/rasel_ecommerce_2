# Instrucciones para agentes

RaSel es una tienda online Django en producción. Estas instrucciones son el
contrato de mantenimiento del repositorio.

## Lectura obligatoria

1. Leer `docs/CURRENT_SYSTEM.md` antes de analizar o modificar el proyecto.
2. Leer también `docs/OPERATIONS.md` si la tarea toca infraestructura,
   variables de entorno, despliegues, administración, pedidos o recuperación.
3. Consultar `docs/CHANGELOG.md` solo para antecedentes de cambios anteriores.

## Documentación como parte del cambio

La documentación describe el estado actual, no ideas futuras. Nunca incluir
secretos, tokens, contraseñas, CBU ni claves de variables de entorno.

| Impacto del cambio | Actualización obligatoria |
| --- | --- |
| Comportamiento visible, modelo de datos o integración externa | `docs/CURRENT_SYSTEM.md` y `docs/CHANGELOG.md` |
| Deploy, variables, administración, operación, monitoreo o recuperación | `docs/OPERATIONS.md` y `docs/CHANGELOG.md` |
| Refactor interno sin impacto observable | No requiere cambios documentales; indicarlo al entregar |

Antes de cerrar una tarea, comprobar que los documentos afectados describen el
resultado final y que el changelog registra los cambios funcionales,
operativos o de configuración.

Si el código, los paneles de producción y la documentación difieren, no asumir
cuál es correcto: verificar la fuente operativa y corregir la documentación en
el mismo cambio que resuelva la diferencia.
