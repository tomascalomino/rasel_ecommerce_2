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

## Versionado obligatorio

- `app_version` en la raíz es la única fuente de verdad de la versión SemVer.
- Todo commit creado durante el desarrollo debe incrementar la versión e incluir
  el cambio del archivo, incluso si solo modifica documentación o configuración.
- El merge commit generado por GitHub al promover `bundle_work` es la única
  excepción: conserva la versión y el árbol exactos del candidato aprobado.
- Usar `python scripts/bump_version.py patch` para correcciones, documentación
  o refactors compatibles; `feature` para funcionalidad compatible; `major`
  para cambios incompatibles; también se acepta una versión exacta mayor.
- Nunca reducir ni reutilizar una versión. El hook local y el workflow de CI
  rechazan commits que no cumplan esta regla.

## Promoción entre ramas

- Todo desarrollo se commitea y publica primero en `bundle_work`; no hacer push
  directo a `main`.
- Esperar el deploy automático de staging y validar allí el cambio antes de
  proponerlo para producción.
- Promover únicamente mediante un pull request `bundle_work` → `main`. Los
  status checks `app-version` y `promotion-gate` deben finalizar correctamente.
- El agente puede abrir o actualizar el PR en borrador, pero `@tomascalomino`
  debe aprobar personalmente cada SHA candidato mediante el check
  `owner-approval` y el Environment protegido de GitHub. Cada nuevo push exige
  una aprobación nueva.
- Ningún agente puede aprobar o rechazar el deployment, iniciar todos los jobs
  pendientes, saltar la protección del Environment ni simular esa decisión por
  API, conector, CLI o interfaz.
- La aprobación no activa un merge automático. El responsable puede ejecutar
  **Create a merge commit** o pedirlo explícitamente a un agente una vez que
  GitHub muestre `owner-approval`, `app-version` y `promotion-gate` en verde.
- Después del merge y antes de otro desarrollo, avanzar `bundle_work` por
  fast-forward al nuevo commit de `main`. Confirmar que ambas ramas apunten al
  mismo SHA y árbol; no usar reset ni force-push.
- Producción se despliega manualmente desde el commit aprobado de `main`; nunca
  desplegar desde `bundle_work` ni activar Auto-Deploy en el servicio productivo.

Si el código, los paneles de producción y la documentación difieren, no asumir
cuál es correcto: verificar la fuente operativa y corregir la documentación en
el mismo cambio que resuelva la diferencia.
