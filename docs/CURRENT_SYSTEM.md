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
  servicio productivo tiene **Auto-Deploy desactivado** y solo debe desplegar
  manualmente un commit de `main` después de aprobar la misma versión en
  staging. Antes del próximo deploy productivo se debe confirmar en Render que
  la rama vinculada ya sea `main`; si todavía figura `bundle_work`, el deploy
  queda bloqueado hasta corregirla.
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
| `shop` | Categorías, productos, variantes, catálogo público, home, SEO y health check. |
| `cart` | Carrito por sesión de navegador; no existe cuenta de cliente. |
| `orders` | Checkout, órdenes, ítems, estados, stock, administración y emails. |
| `shipping` | Zonas, reglas de código postal, puntos de retiro y cotización. |
| `payments` | Checkout Pro, reservas temporales, webhooks firmados, conciliación, borradores y auditoría de Mercado Pago. |
| `config` | Settings, URLs, administración RaSel, roles y contexto global. |

## Catálogo y carrito

- Un **Producto** puede tener varias **Variantes**. El precio y el stock viven
  en la variante; los packs pueden referenciar una variante unitaria para
  calcular ahorro.
- La sección **Nuestra selección** del inicio muestra hasta tres productos
  activos ordenados alfabéticamente por nombre. Con el catálogo actual, esto
  coloca primero las botellas y después los packs.
- La navegación pública se presenta como **Tienda**, **Virgen Extra**,
  **Quiénes Somos**, **Conservación** y **Contacto**. El hero del inicio
  identifica el origen como “Andalgalá, Catamarca”, describe el producto como
  aceite de oliva premium y destaca “Acidez menor a 0,3%” junto a sus otros
  beneficios. El footer conserva la información institucional y legal sin un
  badge adicional de producto. El header usa una versión recortada y
  transparente del logo para aprovechar el espacio existente sin aumentar la
  altura de la barra; el archivo original se conserva como respaldo.
- El administrador activa o desactiva productos y variantes. Las imágenes de
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
- **Descuento por medio de pago:** transferencia y efectivo reciben un descuento
  mínimo del 5% sobre los productos. Para cada variante se calcula el 5% y su
  precio promocional se redondea hacia abajo al múltiplo de $50; la diferencia
  efectiva se multiplica por la cantidad comprada. El costo de envío no se
  descuenta y el umbral de envío gratis continúa evaluándose sobre el subtotal
  de lista. Mercado Pago conserva el precio completo. El detalle de producto
  muestra el precio promocional de la presentación elegida. Las tarjetas del
  inicio, la tienda y las recomendaciones muestran debajo del precio de lista el
  importe exacto por transferencia o efectivo de la variante activa más
  económica. El resumen del checkout cambia en el acto al seleccionar cada
  medio.
- Las tarjetas con stock ofrecen **Compra rápida**. El botón abre un modal con
  imagen, precio, precio offline, cantidad y las presentaciones activas que
  tengan stock. Si solo hay una disponible queda preseleccionada sin mostrar un
  selector. Al agregar, el cliente permanece en la página de origen, ve el
  mensaje de confirmación y el contador del carrito se actualiza.
- **Mercado Pago Checkout Pro:** el flujo está habilitado en producción con
  `MP_CHECKOUT_ENABLED=1`. Usa redirección alojada por Mercado
  Pago; RaSel no recibe tarjetas ni utiliza la Public Key. Ofrece tarjeta,
  débito y dinero en cuenta, hasta seis cuotas, y excluye pagos `ticket`. La
  cuenta vendedora está configurada para liberar el dinero a los **18 días
  corridos**; las cuotas disponibles para el comprador tienen interés y RaSel
  no ofrece cuotas sin interés financiadas por el comercio. Cuando el checkout
  está activo, la página de cada producto muestra el logo oficial de Mercado
  Pago debajo del precio y el inicio incluye un aviso compacto sobre los medios
  disponibles. Ambos avisos se ocultan con el mismo kill switch para no
  promocionar un medio temporalmente deshabilitado.

Para transferencia o efectivo, el checkout valida todas las variantes y su
stock dentro de una transacción, vuelve a calcular precios y el descuento del
lado del servidor, crea una orden `pending`, descuenta stock, vacía el carrito
y envía la confirmación por email. Transferencia se coordina con el comprobante
por WhatsApp; efectivo se cobra al retirar o recibir. La orden conserva el
subtotal de lista en sus ítems y el descuento aplicado en
`payment_discount_amount`, de modo que el total histórico sea auditable.

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

Los estados operativos son `pending`, `paid`, `shipped`, `cancelled` y
`payment_review`. Además existe un estado financiero separado: pendiente,
aprobado, rechazado, cancelado, reintegro parcial, reintegrado, contracargo o
revisión.

1. Una orden nueva queda `pending` y su stock ya fue descontado.
2. Tras verificar el comprobante, el operador la marca `paid` en admin. El
   cliente recibe un email de pago confirmado.
3. Al despachar o dejar listo el retiro, el operador la marca `shipped`. El
   cliente recibe el email correspondiente.
4. Al cancelar desde la acción del admin, el stock se restaura una sola vez.

Una aprobación de Mercado Pago consume la reserva sin descontar stock por
segunda vez. Si el stock ya se había liberado, se intenta reservar nuevamente;
si no alcanza, se crea una orden `payment_review`, no se promete entrega y se
envía una alerta. Reintegros y contracargos se sincronizan sin reponer stock de
forma automática.

Cada email usa un flag de idempotencia: reintentar una acción no debe mandar el
mismo correo dos veces. Las órdenes guardan snapshots de ítems, precios,
descuento por medio de pago, dirección y punto de retiro para preservar su
historial aunque cambie el catálogo o la regla comercial.

## Administración y permisos

`/admin/` es el panel operativo con branding RaSel. Gestiona productos,
variantes, categorías, zonas, reglas postales, puntos de retiro, órdenes y
usuarios.

- **Operador:** puede ver y editar órdenes, catálogo, zonas y puntos de retiro.
- **Solo lectura:** puede consultar los mismos datos sin modificarlos.
- Los usuarios y roles los gestiona un administrador. El dashboard muestra
  pendientes, ventas cobradas y órdenes recientes.
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
  cancelar una aprobación como si eso reintegrara dinero. Una orden enviada no
  repone stock por reintegro hasta confirmar la devolución física.

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
  en `1.0.0`. Todo commit posterior debe incrementarlo. Un hook local y el
  workflow `Version check` rechazan versiones ausentes, inválidas, repetidas o
  decrecientes. La única excepción es la realineación post-squash de
  `bundle_work`: debe conservar exactamente la versión y el árbol Git completo;
  una diferencia en cualquier archivo hace fallar el check.
- `Promotion gate` ejecuta el check y la suite completa para cada PR a `main` y
  acepta solamente `bundle_work` como origen. El ruleset activo `Protect main`
  no tiene bypass, exige PR, historial lineal, conversaciones resueltas y
  squash, y bloquea borrado y force-push. También exige que `app-version` y
  `promotion-gate` finalicen correctamente sobre una rama actualizada antes de
  habilitar el merge.

## Fuentes de verdad

Ante una diferencia, usar esta prioridad:

1. Paneles de producción y comportamiento observable.
2. Código aprobado para producción en `main` y candidato de staging en
   `bundle_work`.
3. Esta documentación, que debe corregirse inmediatamente si quedó desfasada.
