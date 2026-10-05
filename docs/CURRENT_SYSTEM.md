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
| `analytics` | Visitas por sesión, etapas de compra, resúmenes diarios y reportes del admin. |
| `marketing` | Consentimiento publicitario opcional, Meta Pixel y cola persistente de Purchase por Conversions API. |

## Catálogo y carrito

- Un **Producto** puede tener varias **Variantes**. El precio y el stock viven
  en la variante; los packs pueden referenciar una variante unitaria para
  calcular ahorro.
- Cada variante puede tener un **precio regular** y un **texto de promoción**.
  Ambos son opcionales pero deben cargarse o vaciarse juntos, y el precio
  regular debe superar al de venta. Inicio, tienda, recomendaciones, detalle y
  compra rápida agrupan la oferta en un panel: **Precio de lista** acompaña el
  importe regular tachado y debajo se muestra el texto administrable en
  mayúsculas, sin alterar el valor guardado. El precio de venta se identifica
  con “Pagando a través de” y el logo de Mercado Pago cuando ese checkout está
  disponible; su burbuja verde calcula el ahorro contra el precio de lista,
  redondeado al entero más cercano y con **<1% OFF** para diferencias menores a
  0,5%. La sección principal de efectivo o transferencia usa un fondo oliva
  suave y muestra **X% OFF ADICIONAL**, donde X es exactamente el porcentaje
  global configurado en admin, aunque el redondeo del importe hacia abajo al
  múltiplo de $50 pueda mejorar el ahorro efectivo. Esa segunda burbuja también
  aparece sin campaña de lista; con 0% se oculta toda la sección offline. En tarjetas,
  todos los importes pertenecen a la misma variante activa más económica; en
  detalle y compra rápida cambian juntos al elegir la presentación. El botón
  **Comprar** de las tarjetas usa un oliva medio, ligeramente más claro que los
  demás botones principales, manteniendo texto blanco y hover oscuro. Estos
  comparativos no aparecen en carrito, checkout, órdenes ni emails y nunca
  modifican por sí mismos el importe cobrado.
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
- La portada del inicio diferencia su contenido por ancho de pantalla. Hasta
  768 px muestra el video de la botella sirviendo aceite sobre guacamole,
  completo en proporción 16:9, y debajo conserva origen, título, descripción,
  botones y beneficios sobre fondo crema con texto oscuro. El MP4 H.264 de
  1280 × 720 dura unos doce segundos, no tiene audio y pesa aproximadamente
  558 KB; se sirve como estático versionado con WhiteNoise. Se reproduce en
  bucle dentro de la página y ofrece **Pausar video / Reanudar video**. Se pausa
  al salir de pantalla o al ocultar la pestaña, conservando una pausa elegida
  por el visitante. Un fotograma WebP queda como alternativa sin JavaScript,
  ante bloqueo de reproducción o error, con movimiento reducido y con ahorro
  de datos cuando el navegador lo informa. Estos dos últimos ajustes evitan
  cargar el MP4. Desde 769 px se conserva la foto original y no se carga el
  video ni su fotograma. El encabezado usa el menú compacto hasta 1200 px para
  evitar desbordes en anchos intermedios; la navegación completa se muestra
  por encima de ese límite.
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
  con un texto de promoción administrable; ambos campos se cargan o retiran
  juntos. En las vidrieras, los importes forman un panel delineado: arriba
  aparecen **Precio de lista**, el regular tachado y la campaña en mayúsculas.
  El precio de venta ocupa el nivel intermedio, lleva el OFF calculado contra el
  regular y se identifica con “Pagando a través de” y el logo horizontal
  transparente de Mercado Pago cuando ese checkout y el descuento offline están
  activos. El importe exacto por efectivo o transferencia aparece debajo como
  precio principal en verde oscuro, sobre un fondo oliva suave, y lleva la tasa
  global administrable como **X% OFF ADICIONAL**. En móvil, importes, insignias y
  medios de pago se ajustan o envuelven sin superponer precios de cinco cifras.
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

## Campañas de envío gratis en CABA

- **Envíos → Promociones de envío** permite preparar campañas deshabilitadas,
  con título, introducción, inicio y fin en horario argentino. La duración
  sugerida es siete días; el inicio se incluye y el fin es exclusivo. Habilitar
  publica una URL permanente y bloquea fechas y contenido. Se conservan los
  estados borrador, programada, vigente, suspendida y finalizada; no se borran
  campañas desde admin. Activaciones concurrentes se serializan mediante el
  registro único de configuración comercial y rechazan períodos superpuestos.
- La excepción temporal beneficia solo códigos numéricos o CPA válidos de
  CABA con entrega a domicilio por reparto propio, sin depender del nombre de
  la zona compartida con Moreno. No requiere mínimo, admite todos los productos
  con stock y medios habilitados y se acumula con las ofertas existentes. No
  cambia tarifas ni umbrales habituales; Moreno, GBA, correo y retiro conservan
  sus reglas. Los prefijos CPA contradictorios se rechazan en checkout.
- La cotización pública agrega metadata opcional de campaña y una constancia
  firmada ligada al CP, subtotal y condiciones de envío. El POST vuelve a
  comprobarla después de validar stock dentro de la transacción. Si falta o
  cambió, muestra el resumen actualizado, conserva los datos y requiere otra
  confirmación antes de crear el pedido, reservar stock o generar un pago.
  También funciona sin JavaScript. Cotizar o dejar abierto el carrito no
  reserva el beneficio.
- Pedido y borrador conservan campaña, título histórico, instante de aplicación
  y costo habitual del envío. Mercado Pago copia esos snapshots a la orden al
  aprobar. Pagar, conciliar o entregar después del cierre no recalcula importes;
  una reserva vencida no transfiere el beneficio a una compra nueva. Los campos
  de pedidos anteriores quedan vacíos. Admin permite filtrar por campaña y
  consultar ahorro adicional, que es cero si el envío ya era gratuito.
- La franja crema y oliva aparece debajo del header, fuera de su área fija, en
  inicio, catálogo, productos y carrito; checkout comunica el beneficio al
  cotizar. La página `/promociones/<slug>/` conserva fechas y condiciones al
  finalizar. Suspender sustituye el aviso hasta el fin previsto y respeta
  pedidos aceptados. Envíos diferencia la promoción de las tarifas habituales;
  confirmaciones y emails usan snapshots. La página integra la analítica
  existente, sin UTM en enlaces internos.
- Fechas y estados se evalúan por consulta, sin cron ni servicios nuevos.
  `/shipping/promotion-status/` permite refrescar avisos al cruzar fechas y
  volver a una pestaña. Cotización, estado y HTML comercial indican que no se
  cacheen. Las campañas se configuran por separado en staging y producción y
  ninguna migración habilita una promoción. No se agregan datos fiscales; sigue
  vigente la limitación previa del reintento MP ante el primer error 503.

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

## Reportes de visitas y compras

El admin incluye **Reportes** en `/admin/reportes/`, accesible desde su inicio
para administradores y los roles Operador y Solo lectura mediante el permiso
de consulta de reportes. Ofrece hoy, últimos 7, 30 y 90 días, y una evolución
mensual del mes actual y los 11 anteriores, con fechas de Argentina.

- Una visita agrupa la actividad de la misma sesión hasta 30 minutos de
  inactividad. Usa un identificador aleatorio, no identifica personas únicas
  ni une dispositivos. Las recargas suman páginas vistas; el detalle de
  producto alimenta el ranking de fichas más vistas.
- Se registran respuestas HTML exitosas de páginas públicas permitidas. Se
  excluyen staff autenticado, admin, monitoreo, archivos, errores, webhooks,
  páginas con identificadores de pedidos/pagos y bots reconocibles, incluidas
  las comprobaciones de Render identificadas como Go-http-client. El
  filtrado es aproximado y requiere que el navegador conserve la sesión. También
  descarta clientes como okhttp/axios y precargas identificadas por encabezados.
- **Visitas filtradas** conserva el total histórico. **Visitas con actividad**
  cuenta una vez por visita nueva una interacción del navegador, diez segundos
  acumulados con la página visible, un aumento válido de carrito o un checkout
  enviado. No certifica humanidad. Un endpoint POST propio protegido por CSRF
  valida un token firmado por página contra la visita de la sesión; no crea
  visitas ni prolonga su duración. Pestañas de visitas anteriores no activan la
  visita actual. Sin JavaScript o ante errores, la compra sigue funcionando.
- El porcentaje con actividad usa solamente visitas iniciadas con la nueva
  metodología. La evolución muestra **Sin registro** antes de su primera
  medición y avisa que el día inicial es parcial. No se recalculan históricos.
  Calidad del tráfico separa solicitudes descartadas por staff, monitoreo
  reconocido, bots/clientes automatizados, precargas y agente ausente. Los motivos
  son excluyentes. Solo cuenta respuestas HTML públicas medibles; `/healthz`,
  admin, archivos y errores quedan fuera. Dispositivo desconocido no implica bot.
- Las etapas son visita, aumento válido de cantidad en carrito, apertura de
  checkout con carrito y envío válido de checkout. Cada etapa suma una vez
  por visita y se asigna a su fecha de inicio, aunque cruce medianoche. Las
  páginas vistas se asignan al día en que se abren. Las etapas no exigen un
  orden estricto: puede existir un carrito anterior.
- Checkout enviado significa orden offline creada o borrador de Mercado Pago
  reservado, incluso si luego falla la creación de la preferencia. Reintentar
  el pago no suma otra etapa. La escritura analítica ocurre fuera de la
  transacción comercial; sus errores se registran sin revertir compras.
- Las ventas se calculan por fecha de creación de la orden y estado financiero
  actual: aprobadas o parcialmente reintegradas, excluyendo entregas
  canceladas, con envío incluido y reintegros descontados. Los datos de ventas
  se muestran separados de las visitas. La tabla **Compras por origen atribuido**
  usa los mismos pedidos, fechas e importes y reconcilia con las tarjetas de ventas.
  Muestra ocho orígenes principales, el resto agrupado y **Sin atribución**; no
  calcula una tasa de conversión dividiendo ventas por visitas de entrada.
- Una cookie propia firmada conserva el último origen externo o campaña durante
  30 días en el mismo navegador, independientemente de la sesión del carrito.
  Un nuevo contacto externo lo reemplaza; una vuelta directa no lo reemplaza ni
  renueva. Se ignoran referencias internas y retornos de Mercado Pago. La cookie
  es HttpOnly, SameSite=Lax y Secure en producción; no contiene datos del cliente.
  El checkout captura un snapshot opcional con procedencia, fechas e identificador
  técnico de visita en el pedido offline o borrador de Mercado Pago. El pago copia
  ese snapshot a la orden aunque se confirme sin retorno del navegador. Los
  snapshots son metadatos opcionales; no dependen de escrituras analíticas dentro
  de las transacciones comerciales. Webhooks repetidos no duplican ingresos.
  **Sin atribución** incluye pedidos anteriores o sin medición; es distinto de
  **Directo / desconocido**. No hay reconstrucción retroactiva.
- La procedencia usa primero etiquetas de fuente, medio y campaña; sin fuente
  válida usa el dominio de referencia externo o **Directo / desconocido**.
  Las etiquetas aceptan hasta 64 letras latinas sin acento, números, guiones o
  guiones bajos, normalizados a minúsculas. Cada día admite 100 combinaciones
  distintas más **Otros orígenes** para el excedente. Solo se conserva la clase
  de dispositivo: celular, computadora, tablet o desconocido.
- No se guardan IP, URLs completas, agente de usuario completo, datos de
  formularios ni identificadores de pago en las tablas de analítica. El detalle
  de visitas dura 90 días; los resúmenes, el mes actual y 11 meses anteriores.
  Los snapshots técnicos de atribución en órdenes y borradores conservan el mes
  actual y los once anteriores, sin modificar el resto de sus datos comerciales.
  La limpieza se hace por lotes al llegar actividad y también admite ejecución
  manual. Sin actividad puede demorarse hasta la próxima ejecución.
- La fecha inicial corresponde al primer registro exitoso. No hay visitas
  retroactivas. Antes de esa fecha aparece **Sin registro**; los ceros posteriores
  indican ausencia de actividad registrada, que también puede deberse a pausas
  de medición. El panel informa cuando la medición está actualmente pausada.

## Medición publicitaria opcional con Meta

La integración permanece **apagada por defecto** en el código. El 04/10/2026 se
habilitó el píxel en staging y en `https://rasel.ar/`, con la versión productiva
1.11.0 del commit aprobado `8fef46a` (PR #18). Se verificaron las migraciones,
HTTP 200 y la configuración pública con `pixelEnabled=true`, elección inicial
desconocida y `Cache-Control: private, no-store`. El conjunto/píxel es
**RaSel - Tienda online**, ID `1400536168898337`.

CAPI permanece desactivada en ambos entornos porque todavía falta el token.
La recepción real en el Administrador de eventos y la asociación con CP_Rasel
requieren validación del responsable con acceso a Meta. No se enviaron pedidos
ni eventos reales como parte de las pruebas del agente.

- Una franja debajo del header ofrece **OK, aceptar**, **Rechazar** y privacidad.
  No bloquea navegación ni compra. No responder no habilita Meta. La elección
  firmada se conserva durante 180 días por navegador y dominio; se puede cambiar
  desde el footer. La analítica propia funciona independientemente de Meta.
- El script oficial se carga e inicializa únicamente después de aceptación
  vigente. Se desactivan los eventos automáticos del píxel. PageView se emite una
  vez por navegación pública, también al restaurar una página desde el historial
  del navegador. ViewContent usa la variante inicial de la ficha; cambiar la
  presentación no lo repite. Admin, staff, webhooks, endpoints técnicos y páginas
  privadas de pedidos no cargan el píxel ni su fallback sin JavaScript.
- AddToCart utiliza el incremento validado por el servidor, transportado tras
  la redirección mediante un mensaje de sesión de un solo uso. Los aumentos
  desde el carrito también cuentan; quitar o reducir no cuenta. Variantes
  inválidas/inactivas y cantidades inválidas no generan acciones exitosas.
  InitiateCheckout usa un identificador del ciclo del carrito y se reclama una
  vez en el servidor, sin repetir por recargas o errores del formulario. No se
  reclama para carritos con variantes inactivas o cantidades sin stock suficiente.
- Los eventos de navegador usan IDs de variantes, cantidades, precios de venta
  vigentes y ARS. El valor de InitiateCheckout es el subtotal de productos antes
  de elegir/confirmar descuento y envío; no promete el importe final cobrado.
- El checkout asigna un UUID web y captura, solo con aceptación, las cookies
  reales disponibles, User-Agent, URL pública saneada, UTMs y revisión de la
  elección. Conserva la procedencia durante 30 días después de aceptar, ignorando
  enlaces internos y retornos de MP. El borrador MP copia el contexto a la orden.
  No fabrica `_fbp`/`_fbc`, no usa datos de red del webhook/admin y omite IP hasta
  verificar la cadena confiable de Cloudflare/Render. La IP que Meta recibe
  directamente del navegador no depende de esa captura del servidor.
- Una primera aprobación válida de MP —webhook, retorno verificado o
  conciliación— y los cobros offline autorizados usan la misma función de
  registro. Pago y evento pendiente se guardan en una transacción. La fecha
  proviene de la aprobación válida de MP o de la primera confirmación offline;
  sin fecha válida del proveedor se conserva la primera verificación local.
  La orden en revisión no genera Purchase.
- Purchase usa `purchase_<UUID_DEL_CHECKOUT>`, IDs de variantes conservados en
  los ítems, cantidades, precios unitarios históricos antes del descuento por
  medio de pago y `total_amount`: productos después de descuentos más
  envío cobrado por RaSel. Excluye transporte pagado directamente a terceros.
  Solo se envía desde el servidor. Se hashea una vez el email normalizado y el
  teléfono cuando tiene prefijo internacional explícito; cookies y User-Agent
  no se hashean. No se envían nombres ni direcciones completas.
- La cola preserva payload, fecha, valor, destino y modo de prueba en reintentos.
  No hay llamadas a Meta dentro del checkout ni de la confirmación de pago.
  No se reconstruyen históricos ni pedidos del admin; las migraciones no crean
  consentimiento ni eventos retroactivos. La primera confirmación permanece
  registrada incluso después de limpiar la auditoría, evitando reconstrucciones.
- `send_meta_events` diagnostica sin enviar ni limpiar por defecto. Con `--send`
  limpia y despacha lotes mediante reclamos persistentes recuperables. No hay
  cron/worker: envío y reintentos requieren ejecutar el comando. Timeouts y
  errores temporales tienen espera creciente, con límite de 24 horas desde la
  creación del evento. Eventos con aprobación anterior a siete días no se
  envían ni se redatan. Errores permanentes se detienen para revisión.
- Rechazar o revocar detiene nuevos envíos y cancela pendientes de esa elección;
  volver a aceptar no resucita compras anteriores. No se pueden retirar
  solicitudes ya enviadas o en curso. Contexto y payloads se limpian después
  de 90 días; la auditoría mínima dura doce meses, mediante el comando manual.
- El admin muestra fecha de pago y estado resumido de Purchase sin exponer
  payloads ni secretos. La política pública distingue analítica propia de
  publicidad Meta y explica hashes, cookies, conservación y revocación.

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
