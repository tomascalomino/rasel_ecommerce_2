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
- **Render** ejecuta la aplicación Django. Producción se despliega
  automáticamente desde la rama `bundle_work`.
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
- **Pagos activos por defecto:** transferencia bancaria y efectivo contra
  entrega o retiro.
- **Mercado Pago Checkout Pro:** el flujo está implementado, pero se muestra
  únicamente con `MP_CHECKOUT_ENABLED=1`. Usa redirección alojada por Mercado
  Pago; RaSel no recibe tarjetas ni utiliza la Public Key. Ofrece tarjeta,
  débito y dinero en cuenta, hasta seis cuotas, y excluye pagos `ticket`.

Para transferencia o efectivo, el checkout valida todas las variantes y su
stock dentro de una transacción, crea una orden `pending`, descuenta stock,
vacía el carrito y envía la confirmación por email. Transferencia se coordina
con el comprobante por WhatsApp; efectivo se cobra al retirar o recibir.

Para Mercado Pago, el POST del checkout vuelve a validar precios, envío y
stock, descuenta las unidades como reserva por 30 minutos y crea un
`PaymentDraft`. La preferencia vence junto con la reserva y usa una clave de
idempotencia derivada del UUID. Si Mercado Pago no responde, el comprador puede
reintentar mediante POST protegido por CSRF mientras la reserva siga vigente.

El retorno del navegador nunca aprueba pedidos: si contiene un `payment_id`,
RaSel consulta la API y usa el mismo procesador que el webhook. El webhook solo
acepta POST y valida la firma antes de escribir eventos o consultar pagos. Para
aceptar un pago se comparan referencia y metadata, importe exacto, ARS,
collector y `live_mode` contra el endpoint de checkout emitido por Mercado
Pago. Checkout Pro puede devolver `live_mode=true` para cuentas y tarjetas de
prueba que operan mediante el `init_point` regular; el aislamiento se sostiene
además con token de prueba, collector esperado y base staging separada. Pagos
pendientes conservan la reserva y el comando
`reconcile_mp_payments` recupera webhooks perdidos, cancela pendientes al
cumplir 48 horas y libera stock solamente tras consultar al proveedor.

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
dirección y punto de retiro para preservar su historial aunque cambie el
catálogo.

## Administración y permisos

`/admin/` es el panel operativo con branding RaSel. Gestiona productos,
variantes, categorías, zonas, reglas postales, puntos de retiro, órdenes y
usuarios.

- **Operador:** puede ver y editar órdenes, catálogo, zonas y puntos de retiro.
- **Solo lectura:** puede consultar los mismos datos sin modificarlos.
- Los usuarios y roles los gestiona un administrador. El dashboard muestra
  pendientes, ventas cobradas y órdenes recientes.
- Borradores y eventos de Mercado Pago siguen visibles aunque el checkout esté
  apagado. La acción **Reconciliar con Mercado Pago** consulta la API.
- El admin no permite marcar manualmente como pagada una orden Mercado Pago ni
  cancelar una aprobación como si eso reintegrara dinero. Una orden enviada no
  repone stock por reintegro hasta confirmar la devolución física.

## Estado operativo y límites conocidos

- Neon permite restaurar historial de la rama `production` solo dentro de las
  últimas **seis horas**. No hay snapshots ni backups programados configurados.
- Sentry está desactivado; los incidentes se observan en los logs de Render y
  en las entregas de Brevo.
- No existe el Cron Job `rasel-kpi-weekly`; el comando `ops_kpis` puede usarse
  manualmente, pero no corre semanalmente en producción.
- `render.yaml` define `rasel-mp-reconcile` cada diez minutos. Su existencia,
  credenciales y último resultado deben comprobarse en el panel de Render antes
  de habilitar nuevos pagos.
- Render opera en plan gratuito y puede tardar en responder tras inactividad;
  UptimeRobot reduce ese riesgo, pero no reemplaza monitoreo integral.

## Fuentes de verdad

Ante una diferencia, usar esta prioridad:

1. Paneles de producción y comportamiento observable.
2. Código y configuración versionados en `bundle_work`.
3. Esta documentación, que debe corregirse inmediatamente si quedó desfasada.
