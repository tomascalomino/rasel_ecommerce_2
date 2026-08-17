# Historial de funcionamiento

Este historial registra cambios ya aplicados. El comportamiento vigente se
documenta en `CURRENT_SYSTEM.md` y los procedimientos en `OPERATIONS.md`.

## 2026-08-17 — Política de publicación auditada (1.0.3)

- Documentación: se auditó toda la documentación rastreada contra los
  workflows, hooks, scripts de versionado, configuración Django, comandos de
  Render y estado operativo verificado de GitHub y producción.
- Versionado: se explicita que cada commit normal, incluidos documentación y
  configuración, incrementa SemVer; los nombres obligatorios de los status
  checks son `app-version` y `promotion-gate`.
- Promoción: se consolida el único recorrido permitido: `bundle_work`, staging
  automático, PR a `main`, checks verdes, aprobación manual, **Squash and
  merge**, realineación segura y deploy productivo manual.
- Producción: `rasel_ecommerce_2` quedó confirmado en la rama `main`, con
  Auto-Deploy apagado. Cada despliegue debe volver a validar rama, SHA, versión
  y estado del control automático.
- Operación futura: se corrige el Cron Job productivo de conciliación para que,
  cuando se implemente, ejecute `main` y no la rama de staging. También se
  distingue el valor seguro del Blueprint del estado activo en el panel de
  Render.
- Referencias: se verificó que las guías oficiales enlazadas de Checkout Pro,
  webhooks, credenciales, pruebas, salida a producción y Cron Jobs continúan
  disponibles.
- Transferencia: el operador rotó conjuntamente en Render los valores
  productivos de titular, banco, alias y CBU/CVU. No se registran sus valores ni
  se modifican los nombres de las variables existentes.
- Código, migraciones o variables: no cambia el comportamiento de la
  aplicación ni el esquema; el único cambio de configuración es la rotación de
  valores de transferencia informada arriba.
- Documentación actualizada: `AGENTS.md`, `README.md`, la plantilla de PR,
  `docs/CURRENT_SYSTEM.md`, `docs/OPERATIONS.md` y `docs/CHANGELOG.md`.

## 2026-08-16 — Sincronización post-squash segura (1.0.2)

- Corrección: `Version check` distingue los pushes normales de la realineación
  forzada de `bundle_work` posterior a **Squash and merge**. La excepción solo
  acepta el mismo árbol Git completo y exactamente el mismo `app_version`; no
  permite cambios de contenido, otras ramas ni actualizaciones no forzadas.
- Robustez: el workflow recupera explícitamente el commit anterior cuando el
  force-push lo deja fuera de las referencias remotas y devuelve un error claro
  si un rango no puede resolverse.
- Pruebas: se cubren sincronización válida, árbol o versión diferentes, commit
  ausente y SemVer inválido. Los tests del validador se ejecutan dentro del job
  obligatorio `app-version`.
- CI: `actions/checkout` y `actions/setup-python` pasan a sus versiones mayores
  oficiales `v7`, eliminando la advertencia por el runtime Node.js anterior.
- Operación: se documenta la comparación de árboles y el force-push con lease
  exacto que realinea la rama persistente de staging antes del siguiente cambio.
- Migraciones o variables: no se agregan migraciones ni variables de entorno.

## 2026-08-16 — Versionado SemVer visible y obligatorio

- Cambio aplicado: `app_version` se incorpora como fuente única de la versión
  de RaSel y comienza en `1.0.0`; Django valida que exista y use el formato
  estable `MAJOR.MINOR.PATCH`.
- Administración: el encabezado del admin muestra la versión desplegada en
  todas sus páginas y permite identificar el código activo sin consultar
  Render ni Git.
- Flujo de commits: `bump_version.py` incrementa `patch`, `feature`/`minor`,
  `major` o fija una versión exacta mayor. El hook versionado y GitHub Actions
  rechazan commits sin incremento, con formato inválido o con una versión
  repetida o decreciente.
- Promoción: todo cambio pasa primero por `bundle_work` y staging. El workflow
  `Promotion gate` solo admite PRs `bundle_work` → `main` y ejecuta el check y
  la suite completa antes de que el responsable pueda promover la versión con
  **Squash and merge**. Render productivo conserva el deploy manual desde
  `main` como segunda aprobación.
- Verificación: se agregan pruebas para la lectura del archivo y la presencia
  de la versión en el admin; el arranque y `collectstatic` fallan temprano si
  la fuente de versión desaparece o queda inválida.
- Migraciones o variables: no se agregan migraciones ni variables de entorno.
- Configuración externa: el ruleset activo `Protect main` ya exige PR, historial
  lineal, resolución de conversaciones y squash, sin bypass, y bloquea borrado
  y force-push. También exige los status checks `app-version` y
  `promotion-gate` y que la rama esté actualizada antes del merge. La
  vinculación de `rasel_ecommerce_2` a `main` y Auto-Deploy apagado quedó
  confirmada posteriormente el 16 de agosto de 2026.
- Documentación actualizada: `AGENTS.md`, `README.md`,
  `docs/CURRENT_SYSTEM.md`, `docs/OPERATIONS.md` y `docs/CHANGELOG.md`.

## 2026-08-16 — Rotación productiva de Mercado Pago validada

- Cambio operativo: se reemplazaron directamente en Render el Access Token y
  la clave del webhook productivos por los de la cuenta vendedora activa, sin
  exponer ni versionar sus valores. `MP_ENVIRONMENT` permanece en `production`
  y el checkout quedó habilitado con `MP_CHECKOUT_ENABLED=1`.
- Verificación: `healthz` respondió `200`, el GET del webhook respondió `405` y
  una compra real controlada produjo una sola orden pagada, descuento cero,
  un único descuento de stock y un evento firmado procesado sin error.
- Reintegro: el reintegro total se sincronizó en la misma orden y el producto y
  la variante temporales quedaron inactivos, sin una venta neta pendiente.
- Operación: continúa la conciliación manual intensiva durante las primeras 48
  horas y la rutina diaria posterior porque todavía no existe el Cron Job
  productivo `rasel-mp-reconcile`.
- Migraciones o código: no se modificaron código, esquema ni nombres de
  variables; el cambio se limitó a configuración productiva y documentación.
- Documentación actualizada: `docs/CURRENT_SYSTEM.md`, `docs/OPERATIONS.md` y
  `docs/CHANGELOG.md`.

## 2026-08-09 — Logo del header con área visible ampliada

- Cambio aplicado: el header usa una versión WebP transparente, sin pérdida y
  recortada alrededor del contenido real del logo.
- Experiencia: la marca ocupa mejor las cajas existentes de escritorio y móvil
  sin aumentar la altura del header ni desplazar la navegación.
- Respaldo: se conserva el asset original y no se redibujaron la tipografía,
  los ornamentos ni los colores de la marca.
- Migraciones o variables: no se agregan migraciones ni variables nuevas.
- Documentación actualizada: `docs/CURRENT_SYSTEM.md` y `docs/CHANGELOG.md`.

## 2026-08-09 — Baja acidez destacada en el hero

- Cambio aplicado: la descripción principal deja de presentar el aceite como
  “pensado para uso diario” y conserva la definición breve “Aceite de oliva
  premium”.
- Experiencia: la barra de beneficios del hero incorpora “Acidez menor a 0,3%”
  con un ícono de verificación y el mismo estilo responsive existente.
- Migraciones o variables: no se agregan migraciones ni variables nuevas.
- Documentación actualizada: `docs/CURRENT_SYSTEM.md` y `docs/CHANGELOG.md`.

## 2026-08-09 — Simplificación de navegación y textos institucionales

- Cambio aplicado: el hero identifica el origen como “Andalgalá, Catamarca”,
  sin el prefijo “Blend”, y se eliminó el badge “Blend Catamarca” del footer.
- Navegación: **Quiénes Somos** aparece antes de **Conservación**, manteniendo
  enlaces, estados activos y el resto del menú sin cambios.
- Migraciones o variables: no se agregan migraciones ni variables nuevas.
- Documentación actualizada: `docs/CURRENT_SYSTEM.md` y `docs/CHANGELOG.md`.

## 2026-08-09 — Compra rápida desde las tarjetas de producto

- Cambio aplicado: las tarjetas del inicio, la tienda y las recomendaciones
  incorporan un botón **Comprar** que abre un modal sin exigir entrar al detalle.
- Experiencia: el modal muestra imagen, precio de lista, precio offline,
  cantidad y únicamente las presentaciones activas con stock; cuando hay una
  sola disponible queda preseleccionada.
- Carrito: el formulario reutiliza el POST protegido por CSRF y vuelve de forma
  segura a la página de origen, donde se actualizan el mensaje y el contador del
  carrito. Las URLs externas de retorno se rechazan.
- Migraciones o variables: no se agregan migraciones ni variables nuevas.
- Documentación actualizada: `docs/CURRENT_SYSTEM.md` y `docs/CHANGELOG.md`.

## 2026-08-09 — Precio offline en todas las tarjetas de producto

- Cambio aplicado: las previews del inicio, la tienda y las recomendaciones
  muestran el precio de lista y debajo el importe exacto pagando por
  transferencia o efectivo.
- Consistencia: todas las tarjetas comparten la preparación de precio mínimo,
  precio offline y stock a partir de variantes activas; el importe promocional
  reutiliza la regla central de descuento y redondeo.
- Experiencia: se retiró del inicio el banner general de descuento para evitar
  duplicar el beneficio que ahora comunica cada producto. El detalle dinámico y
  el aviso de Mercado Pago no cambian.
- Migraciones o variables: no se agregan migraciones ni variables nuevas.
- Documentación actualizada: `docs/CURRENT_SYSTEM.md` y `docs/CHANGELOG.md`.

## 2026-08-07 — Botellas primero en la selección del inicio

- La sección **Nuestra selección** deja de heredar el orden alfabético
  inverso del modelo y selecciona hasta tres productos activos por nombre
  ascendente.
- Con el catálogo actual aparecen primero las botellas de 250 ml y 500 ml, y
  luego el primer pack; la tienda conserva sus controles de orden propios.
- No requiere migraciones ni cambios de datos.

## 2026-08-07 — Precio offline redondeado por variante

- Cambio comercial: transferencia y efectivo conservan un descuento mínimo del
  5%; después de aplicarlo, el precio promocional de cada variante se redondea
  hacia abajo al múltiplo de $50.
- Consistencia: el checkout multiplica el precio promocional unitario por la
  cantidad, por lo que coincide con el valor mostrado en producto aun al comprar
  varias unidades o presentaciones. Mercado Pago y el envío no reciben descuento.
- Comunicación: inicio, producto, checkout, totales, emails y términos indican
  “mínimo 5%” y muestran el importe efectivo descontado.
- Migraciones o variables: no se agregan migraciones ni variables nuevas; tasa
  y múltiplo permanecen centralizados en `config/pricing.py`.
- Documentación actualizada: `docs/CURRENT_SYSTEM.md`, `docs/OPERATIONS.md` y
  `docs/CHANGELOG.md`.

## 2026-08-07 — Descuento de 5% por transferencia y efectivo

- Cambio comercial: transferencia y efectivo aplican un 5% de descuento sobre
  los productos; el envío mantiene su valor y Mercado Pago conserva el precio
  completo.
- Experiencia: el inicio incorpora dos viñetas compactas y centradas para el
  descuento y Mercado Pago, con el 5% destacado en alto contraste. En el detalle
  de producto ambos avisos reducen considerablemente su altura; el precio
  promocional sigue en negrita y se actualiza al cambiar de presentación. El
  checkout recalcula visualmente descuento y total al alternar el medio de pago.
- Seguridad e historial: el servidor recalcula precios y descuento dentro de la
  transacción de stock. La orden guarda `payment_discount_amount`, los emails y
  pantallas posteriores desglosan subtotal, descuento, envío y total, y los
  ítems conservan el precio de lista.
- Datos: se agrega la migración `orders.0014`; las órdenes existentes y de
  Mercado Pago quedan con descuento cero.
- Verificación: `manage.py check`, `makemigrations --check` y las 88 pruebas de
  `shop`, `cart`, `orders`, `payments` y `shipping` finalizaron correctamente
  (una prueba dependiente de PostgreSQL se omite en SQLite).

## 2026-08-07 — Lanzamiento inicial de Mercado Pago con conciliación manual

- Operación de despliegues: se desactivó Auto-Deploy en `rasel_ecommerce_2`.
  Los cambios se publican primero automáticamente en staging y solo llegan a
  `rasel.ar` mediante un deploy manual después de la aprobación explícita.
- Se incorporó el logo horizontal oficial de Mercado Pago debajo del precio en
  el detalle de producto y un aviso compacto en el inicio. Los dos elementos
  aparecen únicamente cuando el checkout de Mercado Pago está habilitado.
- Decisión comercial: la cuenta productiva de Checkout queda configurada para
  liberar el dinero a los 18 días corridos. Se mantienen cuotas con interés
  para el comprador y no se habilitan cuotas sin interés financiadas por
  RaSel. Al decidirlo, el panel mostraba un costo de 3,39% + IVA para los medios
  ofrecidos.
- Decisión operativa: producción comenzará sin el Cron Job pago de Render. La
  conciliación segura permanece disponible desde el admin y por comando, con
  controles intensivos durante las primeras 48 horas y una rutina diaria
  obligatoria posterior.
- Próximo desarrollo: provisionar `rasel-mp-reconcile` cada diez minutos para
  automatizar webhooks perdidos, pagos pendientes y liberación de reservas. El
  costo mínimo vigente de Render queda aceptado como una mejora futura, no como
  parte del lanzamiento inicial.
- Configuración: el servicio productivo real es `rasel_ecommerce_2`; el
  Blueprint se alinea con ese nombre y deja de declarar el Cron Job para evitar
  su creación y facturación accidental. Mercado Pago continúa apagado con
  `MP_CHECKOUT_ENABLED=0` hasta la compra real controlada.
- Recuperación: se creó en Neon la rama
  `backup-pre-mp-production-2026-08-07` desde el estado actual de `production`,
  con datos y esquema y sin eliminación automática.
- Documentación actualizada: `render.yaml`, `docs/CURRENT_SYSTEM.md`,
  `docs/OPERATIONS.md` y `docs/CHANGELOG.md`.

## 2026-08-07 — Firma sandbox vinculada al vendedor de prueba

- Cambio operativo: se comprobó que las notificaciones reales de Checkout Pro
  sandbox pertenecen a la `TestApp-*` de la cuenta vendedora de prueba y se
  firman con su clave de Webhooks en modo productivo.
- Verificación: un rechazo `OTHE` llegó sin retorno del navegador, respondió
  `200`, liberó stock y creó un evento con firma válida y procesamiento
  correcto.
- Incidente resuelto: usar claves de la aplicación principal producía `401`,
  aunque sus simuladores fueran exitosos. El simulador además reutiliza el ID
  `123456`, por lo que no sustituye una compra sandbox real.
- Migraciones o variables: no se agregan migraciones ni variables; se corrigió
  el origen operativo del valor existente `MP_WEBHOOK_SECRET` de staging.
- Documentación actualizada: `docs/OPERATIONS.md` y `docs/CHANGELOG.md`.

## 2026-08-04 — Webhook fijado por preferencia de Checkout Pro

- Cambio aplicado: cada preferencia incluye la URL HTTPS del webhook de RaSel
  con `source_news=webhooks`, que tiene prioridad sobre la ruta general del
  panel de Mercado Pago.
- Flujo afectado: los cambios de pago pueden llegar sin que el comprador vuelva
  al sitio; el retorno y la conciliación continúan como defensas adicionales.
  Un estado pendiente ahora extiende efectivamente el vencimiento vigente de
  la reserva, manteniendo el límite operativo máximo de 48 horas.
- Migraciones o variables: no se agregan migraciones ni variables; la URL se
  deriva de la `SITE_URL` HTTPS ya obligatoria.
- Documentación actualizada: `docs/CURRENT_SYSTEM.md`, `docs/OPERATIONS.md` y
  `docs/CHANGELOG.md`.

## 2026-08-03 — Liberación manual segura de reservas vencidas

- Cambio aplicado: el admin de borradores incorpora **Conciliar y liberar
  reservas vencidas** para consultar Mercado Pago y reponer stock únicamente
  cuando la reserva venció y no existe un pago.
- Seguridad: una falla de API conserva el stock y registra el error; pagos
  encontrados se procesan mediante el mismo servicio idempotente del webhook.
- Operación: staging puede omitir un Cron Job pago y usar esta acción para sus
  pruebas. El Cron cada diez minutos continúa siendo obligatorio en producción.
- Migraciones o variables: no se agregan migraciones ni variables nuevas.
- Documentación actualizada: `docs/CURRENT_SYSTEM.md`, `docs/OPERATIONS.md` y
  `docs/CHANGELOG.md`.

## 2026-08-03 — Validación de entorno de Checkout Pro

- Cambio aplicado: `live_mode` se valida contra el endpoint de Checkout Pro
  emitido por Mercado Pago, ya que una compra con cuentas y tarjetas de prueba
  mediante el `init_point` regular puede informar `true`.
- Recuperación: una orden puesta en revisión exclusivamente por la regla
  anterior puede reconciliarse a pagada sin crear otra orden, descontar stock
  nuevamente ni repetir el email.
- Seguridad: siguen siendo obligatorios la referencia, metadata, importe, ARS,
  collector, token de prueba y aislamiento de la base staging.
- Migraciones o variables: no se agregan migraciones ni variables nuevas.
- Documentación actualizada: `docs/CURRENT_SYSTEM.md`, `docs/OPERATIONS.md` y
  `docs/CHANGELOG.md`.

## 2026-08-02 — Checkout Pro seguro y conciliable

- Cambio aplicado: se reemplazó el flujo legado de Mercado Pago por Checkout
  Pro con SDK oficial, preferencias idempotentes, reservas de stock, retorno
  verificado por API, webhook firmado antes de toda escritura, estados
  financieros, reintegros sincronizados y revisión manual de anomalías.
- Flujo afectado: checkout, stock, pagos, retornos, webhooks, emails, admin,
  conciliación e incidentes. Transferencia y efectivo conservan su flujo.
- Migraciones o variables: `orders.0013` y `payments.0007`; se sustituye
  `MP_ENABLED` por `MP_CHECKOUT_ENABLED`, ambiente, límites de cuotas/reserva,
  plazo pendiente y email de alertas. Se agrega `mercadopago==3.3.0`.
- Operación: se agrega `reconcile_mp_payments` y el Blueprint declara
  `rasel-mp-reconcile` cada diez minutos. Checkout continúa apagado por defecto
  hasta completar staging, credenciales, webhook, cron y prueba controlada.
- Documentación actualizada: `README.md`, `docs/CURRENT_SYSTEM.md`,
  `docs/OPERATIONS.md` y `docs/CHANGELOG.md`.

## Formato para nuevas entradas

```md
## AAAA-MM-DD — Título breve

- Cambio aplicado: ...
- Flujo afectado: ...
- Migraciones o variables: ...
- Documentación actualizada: ...
```

## 2026-08-02 — Baseline documental auditado

- Cambio aplicado: se reemplazó la documentación histórica fragmentada por una
  descripción del sistema actual, un manual de operación y este historial.
- Flujo afectado: despliegue, catálogo, checkout, pedidos, emails,
  administración, recuperación y servicios externos.
- Migraciones o variables: no se modificaron migraciones ni valores de
  producción; se documentaron las variables existentes.
- Documentación actualizada: `README.md`, `AGENTS.md`, `CLAUDE.md`,
  `docs/CURRENT_SYSTEM.md` y `docs/OPERATIONS.md`.
- Base auditada: `bundle_work` en `384e455`; producción en `rasel.ar`.
