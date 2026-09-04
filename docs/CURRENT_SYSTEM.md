# RaSel: sistema actual

Este documento describe cómo funciona RaSel en producción. Es la fuente de
verdad para el comportamiento actual; no contiene planes futuros ni secretos.

## Producto y arquitectura

RaSel es una tienda de aceite de oliva en `https://rasel.ar`. El recorrido
principal es:

```text
Cliente → Cloudflare (DNS, HTTPS y proxy) → Render (Django/Gunicorn) → Neon (PostgreSQL)
                                      └────→ Cloudflare R2 (imágenes de productos)
Django → Brevo (emails transaccionales)
UptimeRobot → GET https://rasel.ar/healthz
```

- **Cloudflare** administra el DNS, el proxy HTTPS y el bucket público R2.
- **Render** ejecuta la aplicación Django en el servicio productivo
  `rasel_ecommerce_2`. Staging se despliega automáticamente desde la rama
  `bundle_work`; `main` representa el código aprobado para producción. El
  servicio productivo está vinculado a `main`, tiene **Auto-Deploy
  desactivado** y solo despliega manualmente un commit aprobado después de
  validar la misma versión en staging. Esta configuración quedó verificada el
  16 de agosto de 2026; cada despliegue debe volver a comprobar rama, SHA y
  versión antes de promoverlo.
- **Neon** almacena los datos persistentes: catálogo, stock, zonas, puntos de
  retiro, usuarios, pedidos y eventos de pago.
- **R2** guarda las imágenes cargadas desde el admin; los archivos estáticos
  versionados se sirven con WhiteNoise.
- **Brevo** envía la confirmación de pedido, pago confirmado, despacho y el
  aviso interno de nuevas órdenes por API HTTPS.
- **UptimeRobot** mantiene activo el plan gratuito de Render consultando
  `/healthz`. Ese endpoint confirma que Django responde, pero no verifica Neon,
  R2 ni Brevo.

## Aplicaciones Django

| Aplicación | Responsabilidad |
| --- | --- |
| `shop` | Categorías, productos, variantes, configuración comercial, catálogo público, home, SEO y health check. |
| `cart` | Carrito por sesión de navegador; no existe cuenta de cliente. |
| `orders` | Checkout, órdenes, ítems, estados, stock, administración y emails. |
| `shipping` | Zonas, reglas de código postal, puntos de retiro y cotización. |
| `payments` | Checkout Pro, reservas temporales, webhooks firmados, conciliación, borradores y auditoría de Mercado Pago. |
| `config` | Settings, URLs, administración RaSel, roles y contexto global. |

## Catálogo y carrito

- Un **Producto** puede tener varias **Variantes**. El precio y el stock viven
  en la variante; los packs pueden referenciar una variante unitaria para
  calcular ahorro.
- Cada variante puede tener un **precio regular** y un **texto de promoción**.
  Ambos son opcionales pero deben cargarse o vaciarse juntos, y el precio
  regular debe superar al de venta. Inicio, tienda, recomendaciones, detalle y
  compra rápida muestran el texto exactamente como fue cargado dentro de una
  burbuja discreta. Debajo aparecen el precio regular tachado y otra burbuja
  verde con el descuento porcentual derivado del precio regular y el de venta,
  redondeado al entero más cercano. En tarjetas, todos los valores pertenecen a
  la misma variante activa más económica; en detalle y compra rápida cambian
  juntos al elegir la presentación. El comparativo no aparece en carrito,
  checkout, órdenes ni emails y nunca interviene en el importe cobrado.
- La sección **Nuestra selección** del inicio muestra hasta tres productos
  activos ordenados alfabéticamente por nombre. Con el catálogo actual, esto
  coloca primero las botellas y después los packs.
- Debajo de **Nuestra selección**, el inicio muestra avisos compactos del mismo
  tamaño en escritorio: Mercado Pago aparece primero cuando está habilitado y,
  debajo, se ofrecen precios preferenciales para compras mayoristas. En móvil,
  el aviso usa textos breves para no superar el tamaño del bloque de pago ni
  desbordar el contenedor. La consulta abre WhatsApp con un mensaje precargado;
  si el número no está disponible, dirige a **Contacto**. Esa página también
  menciona explícitamente las consultas por compras mayoristas, sin publicar
  porcentajes, mínimos ni listas de precios.
- La navegación pública se presenta como **Tienda**, **Virgen Extra**,
  **Quiénes Somos**, **Conservación** y **Contacto**. El hero del inicio
  identifica el origen como “Andalgalá, Catamarca”, describe el producto como
  aceite de oliva premium y destaca “Acidez menor a 0,3%” junto a sus otros
  beneficios. El footer conserva la información institucional y legal sin un
  badge adicional de producto. El header usa una versión recortada y
  transparente del logo para aprovechar el espacio existente sin aumentar la
  altura de la barra; el archivo original se conserva como respaldo. El
  buscador del encabezado integra campo y lupa en una única píldora, sin sombra
  exterior, y ocupa todo el ancho del panel de navegación en móvil.
- Las vistas previas al compartir cualquier página en WhatsApp y otras redes
  usan una portada JPEG de 1200 × 800 basada en la fotografía real de la
  botella y el aceite. Los metadatos Open Graph y Twitter declaran esa imagen,
  sus dimensiones y un texto alternativo descriptivo.
- El administrador activa o desactiva productos y variantes, y permite editar
  juntos el precio de venta, el precio regular y el texto de promoción. Rechaza campañas
  incompletas o un precio regular que no sea mayor al vigente. Las imágenes de
  producto se cargan desde el admin y quedan en R2 en producción.
- El carrito se guarda en la sesión del navegador con `variant_id` como clave.
  No hay login, persistencia entre dispositivos ni reserva de stock al agregar
  al carrito.

## Checkout, envíos y pagos

El checkout es invitado: recopila contacto y entrega, calcula el envío del lado
del servidor y nunca confía en el total enviado por el navegador.

- **Entrega a domicilio:** la zona se resuelve con el código postal y las
  reglas configuradas en admin. Puede ser gratis, tener precio, requerir un
  mínimo de compra o quedar a coordinar con el comprador.
- **Retiro:** usa un punto de retiro activo, no cobra envío y no requiere
  dirección del cliente.
- **Pagos activos en producción:** transferencia bancaria, efectivo contra
  entrega o retiro y Mercado Pago Checkout Pro.
- **Descuento por medio de pago:** transferencia y efectivo reciben el descuento
  global configurado en el admin, inicialmente 10% sobre los productos.
  Admite enteros de 0 a 50. Para cada variante se calcula el porcentaje vigente y
  su precio promocional se redondea hacia abajo al múltiplo de $50; la diferencia
  efectiva se multiplica por la cantidad comprada. El costo de envío no se
  descuenta y el umbral de envío gratis continúa evaluándose sobre el subtotal
  del precio de venta vigente. Mercado Pago conserva ese precio completo; el
  precio regular tachado es solo informativo. Cada variante puede acompañarlo
  con un texto de promoción administrable, mostrado dentro de una burbuja; ambos
  campos se cargan o retiran juntos. En las vidrieras, los importes forman un
  panel delineado: arriba aparece el precio regular tachado con el porcentaje
  promocional; el precio de venta ocupa un nivel intermedio identificado por el
  texto y el logo horizontal transparente de Mercado Pago cuando ese checkout y
  el descuento offline están activos; el importe exacto por transferencia o
  efectivo aparece debajo como precio principal en verde oscuro, separado por
  una línea y acompañado por “Mejor precio”. La insignia del porcentaje offline
  no se repite en este bloque para no confundirla con el descuento calculado
  entre precio regular y precio de venta. En móvil, cada importe conserva el
  ancho que necesita y la leyenda del medio de pago se adapta al espacio
  restante, evitando que los precios de cinco cifras se superpongan al texto.
  El resumen del
  checkout cambia en el acto al seleccionar cada medio. La comunicación pública
  restante muestra el porcentaje configurado sin la palabra “mínimo”. Con 0% no
  se aplica el redondeo ni descuento, se oculta el importe offline y el precio de
  venta vuelve a ser el principal; los medios offline continúan disponibles.
- Las tarjetas con stock ofrecen **Compra rápida**. El botón abre un modal con
  imagen, precio, precio offline, cantidad y las presentaciones activas que
  tengan stock. Si solo hay una disponible queda preseleccionada sin mostrar un
  selector. Tanto allí como en el detalle, el selector de presentación muestra
  el precio por transferencia o efectivo cuando existe; con descuento offline
  en 0% muestra el precio de venta. Ese texto no cambia el importe base usado
  por carrito, checkout o Mercado Pago. Al agregar, el cliente permanece en la
  página de origen, ve el
  mensaje de confirmación y el contador del carrito se actualiza.
- **Mercado Pago Checkout Pro:** el flujo está habilitado en producción con
  `MP_CHECKOUT_ENABLED=1`. Usa redirección alojada por Mercado
  Pago; RaSel no recibe tarjetas ni utiliza la Public Key. Ofrece tarjeta,
  débito y dinero en cuenta, hasta seis cuotas, y excluye pagos `ticket`. La
  cuenta vendedora está configurada para liberar el dinero a los **18 días
  corridos**; las cuotas disponibles para el comprador tienen interés y RaSel
  no ofrece cuotas sin interés financiadas por el comercio. Cuando el checkout
  está activo y existe un precio offline diferenciado, las vidrieras identifican
  el precio de venta con el logo oficial horizontal de Mercado Pago, sin fondo.
  El inicio incluye además un aviso compacto
  encabezado “Pagá como prefieras” sobre los medios disponibles. Estos avisos se
  ocultan con el mismo kill switch para no promocionar un medio temporalmente
  deshabilitado; en ese caso el importe intermedio se rotula “Precio de venta”.

Para transferencia o efectivo, el checkout valida todas las variantes y su
stock dentro de una transacción, vuelve a calcular precios y el descuento del
lado del servidor, crea una orden con pago y entrega pendientes, descuenta stock, vacía el carrito
y envía la confirmación por email. Transferencia se coordina con el comprobante
por WhatsApp; efectivo se cobra al retirar o recibir. La orden conserva el
subtotal de lista en sus ítems, el descuento aplicado en
`payment_discount_amount` y el porcentaje vigente en
`payment_discount_percent`, de modo que importes, pantallas y emails históricos
no cambien cuando se edite la configuración comercial.

Para Mercado Pago, el POST del checkout vuelve a validar precios, envío y
stock, descuenta las unidades como reserva por 30 minutos y crea un
`PaymentDraft`. La preferencia vence junto con la reserva y usa una clave de
idempotencia derivada del UUID. Cada preferencia fija además el webhook HTTPS
de `SITE_URL` con `source_news=webhooks`; esta ruta específica tiene prioridad
sobre la configuración general de la aplicación y evita depender del retorno
del comprador. Si Mercado Pago no responde, el comprador puede reintentar
mediante POST protegido por CSRF mientras la reserva siga vigente.

El retorno del navegador nunca aprueba pedidos: si contiene un `payment_id`,
RaSel consulta la API y usa el mismo procesador que el webhook. El webhook solo
acepta POST y valida la firma antes de escribir eventos o consultar pagos. Para
aceptar un pago se comparan referencia y metadata, importe exacto, ARS,
collector y `live_mode` contra el endpoint de checkout emitido por Mercado
Pago. Checkout Pro puede devolver `live_mode=true` para cuentas y tarjetas de
prueba que operan mediante el `init_point` regular; el aislamiento se sostiene
además con token de prueba, collector esperado y base staging separada. Pagos
pendientes conservan la reserva. La conciliación manual mediante el admin o el
comando `reconcile_mp_payments` recupera webhooks perdidos, cancela pendientes
al cumplir 48 horas y libera stock solamente tras consultar al proveedor.
Actualmente no existe un Cron Job productivo: hasta incorporarlo, esta
conciliación requiere la rutina manual definida en `OPERATIONS.md`.

## Órdenes, stock y notificaciones

Pago y entrega son estados independientes. El estado financiero puede ser
pendiente, aprobado, rechazado, cancelado, reintegro parcial, reintegrado,
contracargo o revisión. La entrega puede estar pendiente, despachada, lista para
retirar, completada o cancelada.

1. Una orden nueva tiene pago y entrega pendientes y su stock ya fue descontado.
2. Tras verificar un pago offline, el operador usa **Confirmar pago**. Mercado
   Pago solo se aprueba mediante su API o la conciliación.
3. **Despachar / dejar listo para retirar** exige pago aprobado, salvo efectivo
   contraentrega, que puede avanzar con el cobro pendiente.
4. **Marcar como entregado / retirado** finaliza una orden ya cobrada. **Cobrar
   y completar** registra conjuntamente ambos hechos para pagos offline; en
   Mercado Pago solo completa una orden previamente aprobada por la API.
5. Cada etapa envía como máximo un correo: pago, despacho/listo para retirar y
   finalización. La acción conjunta envía únicamente la confirmación final.
6. Al cancelar antes del despacho, el stock se restaura una sola vez. Una orden
   despachada, lista para retirar o completada no repone stock sin devolución
   física confirmada.

Una aprobación de Mercado Pago consume la reserva sin descontar stock por
segunda vez. Si el stock ya se había liberado, se intenta reservar nuevamente;
si no alcanza, la orden queda con pago en revisión y entrega pendiente, no se
promete entrega y se envía una alerta. Reintegros y contracargos se sincronizan
sin reponer stock de forma automática.

Cada email usa un flag de idempotencia: reintentar una acción no debe mandar el
mismo correo dos veces. Las órdenes guardan snapshots de ítems, precios, importe
y porcentaje de descuento por medio de pago, dirección y punto de retiro para
preservar su historial aunque cambie el catálogo o la regla comercial.

## Administración y permisos

`/admin/` es el panel operativo con branding RaSel. Gestiona configuración
comercial, productos, variantes, categorías, zonas, reglas postales, puntos de
retiro, órdenes y usuarios.

- **Operador:** puede ver y editar órdenes, configuración comercial, catálogo,
  zonas y puntos de retiro.
- **Solo lectura:** puede consultar los mismos datos sin modificarlos.
- Los usuarios y roles los gestiona un administrador. El dashboard separa
  cobros pendientes de pedidos para preparar; las ventas se calculan desde el
  estado financiero y descuentan los reintegros parciales.
- El listado de órdenes muestra **Situación**, **Pago** y **Entrega**. Los
  estados son de solo lectura y se cambian mediante acciones contextuales tanto
  dentro de cada orden como sobre una selección del listado.
- El encabezado del admin muestra la versión desplegada con el formato
  `vMAJOR.MINOR.PATCH`. El valor se lee de `app_version` en la raíz del
  repositorio y no depende de una variable de entorno.
- Borradores y eventos de Mercado Pago siguen visibles aunque el checkout esté
  apagado. La acción **Reconciliar con Mercado Pago** consulta la API.
- La acción **Conciliar y liberar reservas vencidas** permite operar staging o
  resolver un incidente manual: consulta Mercado Pago y solo repone stock si
  la reserva ya venció y no existe un pago. Ante un error del proveedor
  conserva el stock y registra el error.
- El admin no permite marcar manualmente como pagada una orden Mercado Pago ni
  cancelar una aprobación como si eso reintegrara dinero. Una orden despachada
  o completada no repone stock por reintegro hasta confirmar la devolución
  física.

## Estado operativo y límites conocidos

- Neon permite restaurar historial de la rama `production` solo dentro de las
  últimas **seis horas**. No hay snapshots ni backups programados configurados.
- La rama Neon `backup-pre-mp-production-2026-08-07` conserva el estado previo
  al lanzamiento productivo de Mercado Pago. No está conectada a Render y no
  debe editarse, restablecerse ni eliminarse durante el período de lanzamiento.
- Sentry está desactivado; los incidentes se observan en los logs de Render y
  en las entregas de Brevo.
- No existe el Cron Job `rasel-kpi-weekly`; el comando `ops_kpis` puede usarse
  manualmente, pero no corre semanalmente en producción.
- Mercado Pago productivo tiene token, webhook y variables operativas de la
  cuenta vendedora activa configurados en `rasel_ecommerce_2`. El checkout está
  habilitado con `MP_CHECKOUT_ENABLED=1` desde el 16 de agosto de 2026, después
  de validar una compra real controlada, una única orden, el descuento de stock,
  la firma del webhook y el reintegro total. La prueba no dejó un producto
  activo ni una venta neta pendiente.
- No existe todavía el Cron Job productivo `rasel-mp-reconcile`. La
  conciliación se opera manualmente y la automatización cada diez minutos queda
  registrada como el próximo desarrollo prioritario.
- Render opera en plan gratuito y puede tardar en responder tras inactividad;
  UptimeRobot reduce ese riesgo, pero no reemplaza monitoreo integral.
- La versión vigente es siempre el valor de `app_version`; el esquema comenzó
  en `1.0.0`. Cada commit creado durante el desarrollo, incluidos documentación,
  configuración y refactors, debe incrementarlo. Un hook local y el workflow
  **Version check** rechazan versiones ausentes, inválidas, repetidas o
  decrecientes. Su job y status check se llaman `app-version`.
- La única excepción es el merge commit generado por GitHub al promover el PR:
  debe tener exactamente dos padres, conservar el árbol y la versión del
  candidato `bundle_work`, y esa versión debe ser mayor que la del `main`
  anterior. El fast-forward posterior de `bundle_work` reutiliza ese mismo
  commit sin crear otro ni cambiar `app_version`.
- El workflow **Promotion gate**, cuyo job y status check se llaman
  `promotion-gate`, ejecuta `manage.py check` y la suite completa para cada PR a
  `main`; acepta solamente `bundle_work` como origen dentro del mismo
  repositorio.
- El workflow **Owner approval** corre en cada push candidato de `bundle_work`.
  Su job `owner-approval` referencia el Environment protegido
  `production-promotion-approval` y queda pendiente hasta que `@tomascalomino`
  lo aprueba personalmente en GitHub. Un nuevo SHA genera otro check y exige una
  decisión nueva; el fast-forward post-merge no solicita aprobación porque ya
  no existen commits por promover.
- El ruleset activo `Protect main` no tiene bypass, exige PR, conversaciones
  resueltas, una rama actualizada y los checks `app-version`, `promotion-gate` y
  `owner-approval`. Permite solo **merge commit** y bloquea borrado y force-push;
  no exige historial lineal ni una review formal del PR porque su autor y el
  único propietario usan la misma identidad de GitHub.
- Los agentes no pueden aprobar o rechazar el deployment, iniciar todos los
  jobs pendientes, saltar la protección del Environment ni simular esa decisión
  mediante ninguna interfaz. La aprobación tampoco activa un merge automático:
  el propietario conserva la acción final o puede pedirla explícitamente a un
  agente después de que los tres checks estén en verde.

## Fuentes de verdad

Ante una diferencia, usar esta prioridad:

1. Paneles de producción y comportamiento observable.
2. Código aprobado para producción en `main` y candidato de staging en
   `bundle_work`.
3. Esta documentación, que debe corregirse inmediatamente si quedó desfasada.
