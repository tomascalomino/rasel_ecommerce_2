# Operación de RaSel

Procedimientos para ejecutar, desplegar y operar la tienda. No almacenar aquí
secretos ni valores reales de configuración.

## Desarrollo local

```powershell
conda activate rasel_ecommerce_venv
pip install -r requirements.txt
python backend/manage.py migrate
python backend/manage.py runserver
```

La aplicación carga `.env` desde la raíz del repositorio. El archivo está
ignorado por Git y nunca debe compartirse. Para pruebas y verificaciones usar:

```powershell
python backend/manage.py check
python backend/manage.py test shop cart orders payments shipping
python backend/manage.py ops_kpis --days 7
```

## Variables de entorno

| Grupo | Variable | Uso | Requerida en producción |
| --- | --- | --- | --- |
| Django | `SECRET_KEY` | Firma criptográfica de Django. | Sí |
| Django | `DEBUG` | Debe ser `0` en producción. | Sí |
| Django | `ALLOWED_HOSTS` | Hosts permitidos, incluidos `rasel.ar` y `www.rasel.ar`. | Sí |
| Django | `SITE_URL` | URL pública para callbacks y CSRF. | Sí |
| Django | `DJANGO_SETTINGS_MODULE` | Módulo de settings de Django. | Sí |
| Django | `LOG_LEVEL` | Nivel de logs de consola. | Sí |
| Django | `SECURE_HSTS_SECONDS` | Tiempo HSTS; tiene valor seguro por defecto. | No |
| Base de datos | `DATABASE_URL` | Conexión PostgreSQL de Neon. | Sí |
| R2 | `R2_BUCKET_NAME` | Activa almacenamiento de media en R2. | Sí |
| R2 | `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Credenciales del bucket. | Sí |
| R2 | `R2_ENDPOINT_URL`, `R2_PUBLIC_DOMAIN` | Endpoint S3 y dominio público de R2. | Sí |
| Media local | `MEDIA_ROOT`, `SERVE_MEDIA` | Fallback local; no es el almacenamiento principal de producción. | No |
| Email | `BREVO_API_KEY` | Envía emails por la API HTTPS de Brevo. | Sí |
| Email | `DEFAULT_FROM_EMAIL` | Remitente verificado de Brevo. | Sí |
| Email | `ORDER_NOTIFICATION_EMAIL` | Destino opcional del aviso interno de nueva orden. | No |
| Email local/legado | `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_HOST`, `EMAIL_PORT` | Backend SMTP alternativo; si faltan, Django usa consola. | No |
| Comercio | `BANK_HOLDER`, `BANK_ALIAS`, `BANK_CBU`, `BANK_NAME` | Datos mostrados para transferencia. | Sí, si se ofrece transferencia |
| Comercio | `WHATSAPP_NUMBER` | Coordinación de comprobantes, entregas y retiros. | Sí |
| Mercado Pago | `MP_CHECKOUT_ENABLED` | Kill switch de pagos nuevos (`0` o `1`). No detiene webhook ni conciliación. | Sí; iniciar en `0` |
| Mercado Pago | `MP_ENVIRONMENT` | Separa estrictamente `test` de `production`. | Sí si se usa MP |
| Mercado Pago | `MP_ACCESS_TOKEN` | Credencial privada usada solo por backend y conciliación. | Sí si se usa MP |
| Mercado Pago | `MP_WEBHOOK_SECRET` | Valida la firma de cada webhook antes de escribir en la base. | Sí si se usa MP |
| Mercado Pago | `MP_MAX_INSTALLMENTS` | Máximo de cuotas; valor operativo inicial `6`. | Sí si se usa MP |
| Mercado Pago | `MP_RESERVATION_MINUTES` | Duración de reserva inicial; valor operativo `30`. | Sí si se usa MP |
| Mercado Pago | `MP_PENDING_MAX_HOURS` | Plazo para conciliar antes de cancelar; valor operativo `48`. | Sí si se usa MP |
| Mercado Pago | `PAYMENT_ALERT_EMAIL` | Destino de anomalías, revisiones y fallas de conciliación. | Sí si se usa MP |
| Monitoreo | `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_ENVIRONMENT` | Integración Sentry, actualmente no configurada. | No |
| Arranque excepcional | `RUN_MIGRATIONS_ON_START` | Ejecuta migraciones al iniciar; normalmente debe quedar apagada. | No |
| Arranque excepcional | `LOAD_FIXTURES` | Fuerza carga única de `fixtures/shop.json` si existe. | No |
| Arranque excepcional | `CREATE_ADMIN`, `ADMIN_USERNAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Crea un superusuario una vez; apagar tras usar. | No |
| Render | `PYTHON_VERSION` | Versión de Python usada por Render. | Sí |
| Render | `PORT` | Puerto inyectado por Render para Gunicorn; no definir manualmente. | Sí, lo provee Render |

Los nombres y valores de producción viven en los paneles de Render, Neon,
Cloudflare y Brevo. Documentar una variable nueva en esta tabla al introducirla.

`MP_CHECKOUT_ENABLED=1` impide el arranque si falta token, secret, ambiente,
email de alertas o si `SITE_URL` no usa HTTPS. La Public Key de Mercado Pago no
se configura en RaSel: Checkout Pro captura los datos de pago en el sitio del
proveedor.

## Alta desde cero de Mercado Pago

### 1. Cuenta vendedora y aplicación

1. Crear o usar una cuenta vendedora argentina y completar identidad, datos
   fiscales, segundo factor y recuperación de cuenta.
2. Entrar en Mercado Pago Developers → **Tus integraciones** → **Crear
   aplicación**.
3. Usar el nombre `RaSel Ecommerce` y seleccionar **Pagos online**, **Tienda
   con desarrollo propio**, sitio `https://rasel.ar`, **Checkouts** y
   **Checkout Pro**.
4. En **Pruebas → Credenciales de prueba**, activar las credenciales si fuera
   necesario. Copiar el Access Token directamente al panel de Render. Nunca
   pegarlo en Git, documentación, logs, capturas ni chats.
5. Crear una cuenta de prueba de tipo comprador, país Argentina. Guardar sus
   datos únicamente en el gestor operativo autorizado.

### 2. Staging aislado

1. Crear una base Neon vacía llamada `rasel-mp-staging`. No clonar producción
   ni copiar clientes, pedidos o credenciales reales.
2. Crear el servicio web Render `rasel-mp-staging`, conectado a la rama de la
   integración, con `bash build.sh` y `bash start.sh`.
3. Configurar `DEBUG=0`, una `SECRET_KEY` propia, `SITE_URL` y `ALLOWED_HOSTS`
   del subdominio staging, la `DATABASE_URL` staging y:

   ```text
   MP_CHECKOUT_ENABLED=0
   MP_ENVIRONMENT=test
   MP_ACCESS_TOKEN=<token de prueba, solo en Render>
   MP_MAX_INSTALLMENTS=6
   MP_RESERVATION_MINUTES=30
   MP_PENDING_MAX_HOURS=48
   PAYMENT_ALERT_EMAIL=<mail no productivo>
   ```

4. No configurar Brevo, R2 ni bases productivas. Si se necesita entrega real
   de alertas, usar credenciales y destinatarios exclusivos de staging.
5. Crear un administrador temporal con `CREATE_ADMIN` y sus variables,
   desplegar una vez, comprobar acceso y eliminarlas inmediatamente.
6. Crear productos, variantes, stock, zonas, reglas postales y puntos de retiro
   totalmente ficticios.

### 3. Webhook de pruebas

1. En la aplicación principal abrir **Credenciales de prueba** y localizar los
   datos de la cuenta vendedora de prueba asociada al Access Token. No usar la
   cuenta compradora ni compartir usuario, contraseña o código.
2. En una sesión de navegador separada, iniciar sesión en Mercado Pago
   Developers con esa cuenta vendedora. Abrir su aplicación automática
   `TestApp-*` → **Webhooks → Configurar notificaciones**.
3. En `TestApp-*`, seleccionar **Modo productivo**, registrar
   `https://<servicio-staging>.onrender.com/payments/webhook/` y dejar marcado
   exclusivamente **Pagos (legacy)**. Las compras Checkout Pro sandbox se
   muestran como productivas dentro de esta cuenta ficticia.
4. Revelar la clave secreta de `TestApp-*` en modo productivo y copiarla
   directamente a `MP_WEBHOOK_SECRET` de staging. Las claves de Webhooks de la
   aplicación principal pueden validar su simulador, pero no las notificaciones
   reales emitidas por el vendedor de prueba.
5. Desplegar con el checkout todavía apagado y verificar que GET al endpoint
   responda `405`.
6. Habilitar temporalmente el checkout y completar un pago sandbox para obtener
   un `mp_payment_id` real asociado a un borrador. En **Simular**, usar ese ID:
   un valor inventado no puede superar la consulta estricta a la API.
7. Confirmar con una compra real sandbox, sin usar **Volver al sitio**, que el
   POST responde `200`, el borrador cambia de estado y en admin el evento tiene
   firma válida y resultado procesado. Una firma inválida debe responder `401`
   y no crear `PaymentEvent`.
8. El simulador reutiliza el identificador de notificación `123456`; una vez
   procesado, nuevas simulaciones pueden responder `200` como duplicadas sin
   volver a consultar otro Data ID. Para validar el flujo completo usar un pago
   sandbox nuevo o un reintento real visible en el panel de `TestApp-*`.
9. Mantener `MP_CHECKOUT_ENABLED=1` solo durante la matriz de staging.

RaSel también envía en cada preferencia
`https://<SITE_URL>/payments/webhook/?source_news=webhooks`. Mercado Pago da
prioridad a esa URL sobre la configurada en el panel. Esto es intencional: las
operaciones se notifican aunque el comprador cierre el navegador o las rutas
de prueba y producción del panel no coincidan. La URL del panel y su clave
secreta siguen siendo obligatorias para validar la firma.

### 4. Matriz obligatoria de staging

Ejecutar en incógnito con el comprador de prueba: aprobación `APRO`, rechazo
`OTHE`, pendiente `CONT`, reintento del mismo borrador, webhook duplicado,
retorno antes y después del webhook, cierre sin retorno, preferencia y reserva
vencidas, pago aprobado tras liberar stock y falta de stock durante revisión.

Además, correr tests automatizados para firma inválida, retorno falsificado,
concurrencia e idempotencia, importe, moneda, collector y `live_mode`
incorrectos, reintegros y kill switch. Confirmar visualmente que no aparecen
Rapipago/Pago Fácil, que sí aparecen tarjeta, débito y dinero en cuenta, y que
el máximo es seis cuotas. Repetir la matriz completa dos veces antes de
producción.

En Checkout Pro, las cuentas y tarjetas de prueba pueden usar el `init_point`
regular y el pago consultado puede informar `live_mode=true`. RaSel valida ese
campo contra el host del checkout que devolvió Mercado Pago y mantiene el
aislamiento mediante credenciales de prueba, collector y base separados; no se
debe cambiar `MP_ENVIRONMENT` a `production` para corregir una prueba.

Staging no necesita un Cron Job pago permanente. Para una preferencia
abandonada, esperar que pase `reservation_expires_at`, seleccionar únicamente
ese borrador en **Payments → Payment drafts** y ejecutar **Conciliar y liberar
reservas vencidas**. La acción consulta Mercado Pago antes de reponer stock; si
encuentra un pago lo procesa, y si la API falla conserva la reserva. Nunca
editar o borrar el borrador ni corregir el stock manualmente.

## Conciliación manual de Mercado Pago

Ejecución manual:

```powershell
python backend/manage.py reconcile_mp_payments --batch-size 100
```

El comando consulta pagos antes de liberar reservas. Recupera aprobaciones cuyo
webhook se perdió, extiende pagos `pending`/`in_process`, y a las 48 horas
solicita su cancelación y verifica el resultado antes de reponer stock. Si la
API falla, conserva el stock, registra el error, envía una alerta y termina con
código distinto de cero.

Producción comienza sin un Cron Job pago. Mientras no exista automatización,
la operación manual es obligatoria:

1. Durante las primeras 48 horas del lanzamiento, revisar cada 30 minutos
   mientras haya actividad comercial.
2. Después, revisar como mínimo al abrir, a mitad de la jornada y antes de
   cerrar, además de hacerlo inmediatamente ante una alerta de pago, un error
   de webhook o una incidencia de Mercado Pago.
3. Entrar en **Payments → Payment drafts**, filtrar estados creados, con stock
   reservado, preferencia creada, pago pendiente o revisión manual, seleccionar
   los borradores y ejecutar **Conciliar y liberar reservas vencidas**.
4. Revisar también órdenes en `payment_review`, eventos con firma o
   procesamiento fallido, stock liberado y `processing_error`.
5. Si la API o la base fallan, mantener o colocar
   `MP_CHECKOUT_ENABLED=0`, conservar el stock y repetir la conciliación cuando
   el proveedor se recupere. Nunca asumir que no hubo pago.

La próxima mejora operativa prioritaria es crear en Render el Cron Job
`rasel-mp-reconcile`, rama `bundle_work`, schedule UTC `*/10 * * * *` y comando
`python backend/manage.py reconcile_mp_payments --batch-size 100`. Render cobra
por tiempo de ejecución con un mínimo de USD 1 mensual por Cron Job al momento
de esta decisión; verificar el precio vigente antes de provisionarlo.
Cuando se incorpore, deberá recibir por separado `DATABASE_URL`, credenciales
MP, ambiente, alertas y Brevo, y probarse manualmente antes de sustituir la
rutina anterior. Hasta entonces no debe agregarse al Blueprint ni asumirse que
la conciliación ocurre sola.

## Salida a producción de Mercado Pago

1. En Mercado Pago abrir **Producción → Credenciales de producción → Activar
   credenciales**. Usar industria **Alimentos y bebidas** o **Retail** si la
   primera no aparece, sitio `https://rasel.ar`, aceptar términos y completar
   reCAPTCHA.
2. Copiar el Access Token productivo directamente al servicio web de Render.
   Configurar `MP_ENVIRONMENT=production` y mantener
   `MP_CHECKOUT_ENABLED=0`.
3. En **Webhooks**, modo productivo, registrar
   `https://rasel.ar/payments/webhook/`, seleccionar solo **Pagos (legacy)** y
   copiar el secret productivo directamente al servicio web.
4. En **Costos y cuotas → Checkout → Por cobro**, mantener la liberación del
   dinero a **18 días corridos** para todos los medios. En **Por ofrecer
   cuotas**, comprobar que indique cuotas con interés para el cliente y no
   activar **Ofrecer cuotas sin interés**. El costo observado al 7 de agosto de
   2026 fue 3,39% + IVA; verificar siempre el valor vigente en la cuenta antes
   de tomar decisiones de precios.
5. Crear un snapshot o punto de recuperación Neon. Para este lanzamiento se
   creó `backup-pre-mp-production-2026-08-07` desde la rama `production`, con
   datos y esquema actuales y sin eliminación automática. Desplegar código y
   migraciones con MP apagado.
6. Ejecutar `check` y la suite de `shop`, `cart`, `orders`, `payments` y
   `shipping`. Verificar health check, tienda, carrito, transferencia y efectivo.
7. Verificar que GET al webhook responda `405` y ejecutar una conciliación
   manual sin errores. Confirmar que el operador acepta y conoce la rutina
   manual mientras no exista el Cron Job.
8. Cambiar `MP_CHECKOUT_ENABLED=1`, desplegar y realizar una compra real
   controlada de bajo importe.
9. Confirmar el webhook firmado productivo, el pago en Mercado Pago,
   exactamente una orden pagada, un único
   descuento de stock, un solo email, retorno correcto, datos de envío y carrito
   limpio.
10. Ejecutar la evaluación de calidad con el `mp_payment_id` productivo de esa
   compra y resolver las observaciones.
11. Monitorear eventos, borradores, logs y alertas, y ejecutar la conciliación
    manual cada 30 minutos durante las primeras 48 horas.

## Reintegros y respuesta a incidentes

Para reintegrar, buscar la orden, copiar `mp_payment_id` y hacer el reintegro
total o parcial desde Mercado Pago. Esperar el webhook y comprobar estado y
monto en RaSel; si no llega, usar **Reconciliar con Mercado Pago**. El sistema
no restaura stock por el reintegro. Si la orden fue enviada, confirmar primero
la devolución física; si no fue enviada, cancelar y reponer desde el admin solo
cuando el estado financiero ya permita hacerlo.

Kill switch: poner `MP_CHECKOUT_ENABLED=0` para ocultar y bloquear pagos nuevos,
pero mantener token, secret, webhook y conciliación manual para terminar
operaciones en curso.
No revertir migraciones ni borrar borradores. Si se expone un secreto,
regenerarlo en Mercado Pago, reemplazarlo en el servicio web y desplegar; nunca
publicar su valor. Un rollback de código solo es seguro con el antiguo
`MP_ENABLED` ausente o en `0` y después de revisar compatibilidad de migraciones.

Referencias operativas: [crear aplicación](https://www.mercadopago.com.ar/developers/es/docs/checkout-pro/create-application),
[credenciales](https://www.mercadopago.com.ar/developers/es/docs/checkout-pro/additional-content/credentials),
[Webhooks de Checkout Pro](https://www.mercadopago.com.ar/developers/es/docs/checkout-pro/payment-notifications),
[compras de prueba](https://www.mercadopago.com.ar/developers/es/docs/checkout-pro/integration-test/test-purchases),
[salida a producción](https://www.mercadopago.com.ar/developers/es/docs/checkout-pro/go-to-production)
y [Cron Jobs de Render](https://render.com/docs/cronjobs).

## Despliegue y rollback

Los pushes a `bundle_work` despliegan automáticamente el servicio de staging.
El servicio productivo `rasel_ecommerce_2` mantiene **Auto-Deploy desactivado**
para que ningún cambio llegue a `rasel.ar` sin revisión previa.

1. Esperar que staging quede `Live` y revisar allí el cambio en escritorio y
   móvil.
2. Obtener la aprobación explícita del responsable del sitio.
3. En `rasel_ecommerce_2`, usar **Manual Deploy → Deploy latest commit** y
   comprobar que el commit coincida con el aprobado en staging.
4. Render ejecuta `bash build.sh`: instala dependencias, corre
   `collectstatic` y aplica migraciones.
5. Render ejecuta `bash start.sh`: entra en `backend/` y arranca Gunicorn con
   dos workers.
6. Confirmar `https://rasel.ar/healthz`, home, catálogo, una imagen de R2 y un
   checkout sin completar una compra real.
7. Revisar logs de Render por errores de inicio, base de datos, R2 o Brevo.

Si un deploy rompe producción, usar el rollback de Render al deploy estable
anterior. No revertir migraciones ni borrar datos sin preparar primero una
recuperación de Neon.

## Operación diaria desde admin

### Catálogo y stock

1. Crear o editar el producto y sus variantes.
2. Mantener precio, SKU, stock, estado activo y relación de packs correctos.
3. Cargar o reemplazar imágenes; confirmar que la URL generada usa R2 y que la
   imagen se ve en listado y detalle público.

### Envíos y retiros

1. Editar zonas, precios, mínimos, reglas de código postal y efectivo permitido
   desde el admin.
2. Mantener exactamente una zona por defecto activa.
3. Editar puntos de retiro activos, dirección e indicaciones antes de ofrecerlos
   al cliente.

### Pedidos

1. Una orden por transferencia o efectivo llega `pending`; una aprobación MP
   llega `paid`, y una anomalía MP llega `payment_review`.
2. Las órdenes por transferencia o efectivo muestran un descuento del 5% sobre
   los productos. Revisar `descuento por medio de pago`, subtotal, envío y total
   antes de cobrar o confirmar; Mercado Pago debe mostrar descuento cero. El
   envío nunca forma parte de la base promocional.
3. Para transferencia, verificar el comprobante recibido por WhatsApp antes de
   marcar la orden como pagada.
4. Marcar `paid` manualmente solo para métodos offline. Las órdenes MP se
   actualizan mediante API y conciliación.
5. Marcar `shipped` cuando se despacha o queda listo para retirar.
6. En una orden MP aprobada, reintegrar primero en Mercado Pago; cancelar en
   RaSel no mueve dinero. No restaurar stock enviado sin devolución física.

Antes de aprobar un despliegue, probar en staging una compra con envío y otra
con retiro: al alternar Mercado Pago, transferencia y efectivo, el resumen debe
mostrar u ocultar el descuento sin recargar la página. Al confirmar, el total de
la orden y del email debe coincidir con el resumen. La tasa promocional es una
regla versionada en `config/pricing.py`; cambiarla requiere código, pruebas,
actualización de la comunicación visible y el flujo staging → aprobación → producción.

## Incidentes frecuentes

| Síntoma | Comprobación y acción |
| --- | --- |
| Sitio lento o dormido | Confirmar que UptimeRobot consulta `/healthz`; revisar estado y logs de Render. |
| Sitio responde pero falla checkout | Revisar logs de Render y la conexión `DATABASE_URL` a Neon. `/healthz` no prueba la base. |
| Imagen faltante | Confirmar el producto en admin, las variables R2 y la existencia del objeto en el bucket; no asumir que `MEDIA_ROOT` local la recuperará. |
| No llega un email | Revisar `BREVO_API_KEY`, remitente verificado, destinatario y registros de Brevo; buscar la excepción en Render. |
| Stock incorrecto | Revisar ítems y estado de la orden; cancelar desde admin restaura stock una vez. |
| Pago aprobado sin orden normal | Buscar el borrador y evento, ejecutar **Reconciliar con Mercado Pago** y revisar `payment_review`; no prometer entrega ni cobrar de nuevo. |
| Pago cambia solo al volver desde Mercado Pago | Comprobar que la preferencia contiene la `notification_url` HTTPS de `SITE_URL` con `source_news=webhooks`, revisar entregas en Webhooks y reconciliar el borrador. No depender del retorno del navegador. |
| Webhook sandbox MP devuelve `401` | Abrir el evento en la `TestApp-*` del vendedor de prueba y comparar su clave de **Modo productivo** con `MP_WEBHOOK_SECRET` de staging. No usar las claves de la aplicación principal. |
| Webhook productivo MP devuelve `401` | Comparar la clave de modo productivo de la aplicación real con Render; rotar y reemplazarla si existe duda de exposición. |
| Conciliación MP falla | Mantener el checkout apagado si el problema persiste, conservar token y webhook, y revisar API, base, alertas y último `processing_error`. Nunca liberar stock suponiendo que no hubo pago. |
| Cambio de deploy fallido | Revisar logs del deploy, volver al último deploy estable y evitar cambios destructivos en la base. |

## Recuperación y monitoreo

- Neon tiene seis horas de restauración desde historial y no tiene snapshots ni
  agenda automática. Antes de una migración o acción de alto riesgo, crear un
  snapshot manual si está disponible y verificar primero los datos con
  **Preview data**. No usar **Restore** directamente sobre producción sin un
  plan de recuperación validado.
- Los logs de Render son la observabilidad activa. Sentry no está configurado.
- `ops_kpis --days 7` sigue siendo manual. La conciliación de Mercado Pago
  también es manual hasta incorporar `rasel-mp-reconcile`; registrar cada
  revisión operativa y no asumir que existe una ejecución programada.
- UptimeRobot es keep-alive, no monitoreo de base de datos, R2, checkout o email.

## Checklist de cambio operativo

- Confirmar qué servicios externos y variables toca el cambio.
- Ejecutar tests y verificaciones relevantes en el entorno Conda.
- Aplicar el cambio y validar el flujo público afectado.
- Actualizar `CURRENT_SYSTEM.md` y/o este documento según `AGENTS.md`.
- Registrar el cambio en `CHANGELOG.md` si modifica comportamiento u operación.
