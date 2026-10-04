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
python backend/manage.py test config shop cart orders payments shipping analytics marketing
python backend/manage.py ops_kpis --days 7
```

## Versionado de la aplicación

`app_version` en la raíz es la única fuente de verdad y contiene una versión
SemVer estable `MAJOR.MINOR.PATCH`. Django valida el archivo al arrancar y el
admin muestra el mismo valor con prefijo `v`.

Todo commit creado durante el desarrollo debe incluir un incremento, incluso si
solo modifica documentación, configuración o un refactor interno. Si un pull
request contiene varios commits, cada uno debe introducir su propio incremento.
Antes de preparar el commit, ejecutar una de estas opciones:

```powershell
# Corrección, documentación o refactor compatible: 1.0.0 -> 1.0.1
python scripts/bump_version.py patch

# Funcionalidad compatible: 1.0.1 -> 1.1.0
python scripts/bump_version.py feature

# Cambio incompatible: 1.1.0 -> 2.0.0
python scripts/bump_version.py major

# Versión exacta, siempre mayor que la actual
python scripts/bump_version.py 2.1.0
```

Activar una sola vez por clon el hook incluido en el repositorio:

```powershell
python scripts/install_git_hooks.py
```

El hook rechaza cada commit creado durante el desarrollo si `app_version` no
está preparado, no tiene formato válido o no aumenta. El workflow **Version
check** repite la validación para cada commit de un push o pull request; el job
y status check que debe exigir el ruleset se llama `app-version`. La única
excepción es el merge commit que GitHub crea al promover el PR: debe conservar
exactamente el árbol y la versión del candidato, y esa versión debe ser mayor
que la del primer padre de `main`. La CI no sustituye la protección de rama de
GitHub. No editar el valor desde Render ni crear una variable de entorno
equivalente.

## Flujo obligatorio de ramas y aprobación

`bundle_work` es la rama de desarrollo integrado y la fuente del deploy
automático de staging. `main` contiene exclusivamente versiones aprobadas y es
la única fuente permitida del deploy productivo manual.

| Rama | Función | Despliegue permitido |
| --- | --- | --- |
| `bundle_work` | Integración y validación previa | Staging automático |
| `main` | Código aprobado | Producción manual con Auto-Deploy apagado |

El flujo obligatorio es:

1. Incrementar `app_version` en cada commit y trabajar sobre `bundle_work`.
2. Pushear únicamente a `bundle_work` y esperar que staging quede `Live`.
3. Probar el flujo afectado en staging, incluidos escritorio y móvil cuando
   corresponda.
4. Abrir o actualizar en borrador el pull request `bundle_work` → `main`.
5. El workflow **Owner approval** publica el check `owner-approval` sobre cada
   SHA candidato. Tras validar staging, `@tomascalomino` abre el run pendiente,
   selecciona **Review deployments** y luego **Approve and deploy** para el
   Environment `production-promotion-approval`. Cada nuevo push requiere repetir
   esta aprobación.
6. Esperar también **Version check** y **Promotion gate**. Los status checks
   obligatorios son `owner-approval`, `app-version` y `promotion-gate`; el último
   rechaza otros orígenes y ejecuta `manage.py check` más la suite completa de
   Django. Los agentes no pueden aprobar o rechazar el deployment, iniciar jobs
   pendientes, saltar la protección ni simular la decisión mediante API,
   conector, CLI o UI.
7. La aprobación no activa un merge automático. El propietario ejecuta
   exclusivamente **Create a merge commit** o se lo pide expresamente a un
   agente después de que GitHub muestre la aprobación vigente. No se admite push
   directo a `main`.
8. Verificar que `main`, el PR aprobado y `app_version` identifican el mismo
   candidato antes de iniciar un deploy productivo.
9. Antes de otro desarrollo, avanzar `bundle_work` por fast-forward al merge
   commit de `main` mediante el procedimiento seguro de esta sección.

El ruleset activo `Protect main` apunta a la rama por defecto (`main`), no tiene
bypass, exige pull request, conversaciones resueltas, el método **merge commit**
y una rama actualizada, y bloquea force-push y eliminación. No exige historial
lineal. También requiere `owner-approval`, `app-version` y `promotion-gate`.

El Environment `production-promotion-approval` tiene como único revisor
requerido a `@tomascalomino` y no permite bypass administrativo. Mantiene
desactivado **Prevent self-review** porque la conexión usada para preparar el PR
y el propietario comparten la misma identidad de GitHub; activarlo impediría
también la aprobación humana. Por esa razón, el contrato de agentes prohíbe de
forma absoluta invocar las APIs o controles de aprobación, rechazo o bypass.
Una separación criptográfica completa requeriría una segunda identidad para los
agentes; mientras no exista, el check manual de GitHub y esta prohibición operan
en conjunto.

En la configuración del repositorio se debe habilitar exclusivamente **Allow
merge commits** y deshabilitar **Allow squash merging** y **Allow rebase
merging**. La protección de GitHub controla la promoción de código; el deploy
manual de Render agrega una segunda aprobación.

### Sincronización post-merge de `bundle_work`

GitHub crea un merge commit cuyo primer padre es el `main` anterior y cuyo
segundo padre es el candidato de `bundle_work`. Como la rama debe estar
actualizada antes de promoverse, el merge commit conserva exactamente el árbol
y `app_version` del candidato. Antes de empezar otro cambio, avanzar la rama de
staging por fast-forward para que las dos ramas apunten al mismo commit. Ejecutar
solamente con el árbol rastreado limpio:

```powershell
git switch bundle_work
git fetch origin
git merge --ff-only origin/main
git diff --exit-code origin/main bundle_work
git rev-parse origin/main
git rev-parse bundle_work
git rev-parse "origin/main^{tree}"
git rev-parse "bundle_work^{tree}"
git push origin bundle_work
```

Los dos SHA y los dos valores `^{tree}` deben ser iguales; `git diff` no debe
mostrar nada. Si el fast-forward no es posible o cualquier valor difiere,
detenerse: no hacer reset, rebase ni force-push. Esta operación no crea un
commit ni incrementa `app_version`; solo publica en `bundle_work` el mismo merge
commit ya aprobado en `main`.

Después del push, confirmar en GitHub que el job `app-version` terminó en verde
y que `origin/main` y `origin/bundle_work` apuntan al mismo commit. Esa
coincidencia cierra la promoción y deja staging listo para el siguiente cambio.

## Variables de entorno

| Grupo | Variable | Uso | Requerida en producción |
| --- | --- | --- | --- |
| Django | `SECRET_KEY` | Firma criptográfica de Django. | Sí |
| Django | `DEBUG` | Debe ser `0` en producción. | Sí |
| Django | `ALLOWED_HOSTS` | Hosts permitidos, incluidos `rasel.ar` y `www.rasel.ar`. | Sí |
| Django | `SITE_URL` | URL pública para callbacks y CSRF. | Sí |
| Django | `DJANGO_SETTINGS_MODULE` | Módulo de settings de Django. | Sí |
| Django | `LOG_LEVEL` | Nivel de logs de consola. | Sí |
| Meta | `META_PIXEL_ID` | ID público del conjunto/píxel. | Sí, si se activa Meta |
| Meta | `META_PIXEL_ENABLED` | Habilita píxel tras consentimiento; por defecto `0`. | No |
| Meta | `META_CAPI_ENABLED` | Habilita despacho manual de Purchase; por defecto `0`. | No |
| Meta | `META_CAPI_ACCESS_TOKEN` | Credencial privada exclusivamente del backend. | Sí, si se activa CAPI |
| Meta | `META_GRAPH_API_VERSION` | Versión fijada de Graph API; valor inicial `v26.0`. | Sí, si se activa CAPI |
| Meta | `META_TEST_EVENT_CODE` | Código temporal para Probar eventos; vacío en producción. | No |
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
Los valores `BANK_HOLDER`, `BANK_NAME`, `BANK_ALIAS` y `BANK_CBU` deben rotarse
juntos para no mostrar datos de cuentas diferentes. El 17 de agosto de 2026 el
operador actualizó este conjunto en `rasel_ecommerce_2`; sus valores no se
registran en el repositorio. Al cambiarlos, usar **Save and deploy**, esperar
`Live` y verificar una pantalla y un email nuevos de transferencia. Los emails
ya enviados conservan el contenido histórico.

`render.yaml` conserva `MP_CHECKOUT_ENABLED=0` como valor seguro para altas o
recreaciones; no representa el valor operativo del servicio existente, que está
habilitado desde el panel. No sincronizar el Blueprint sobre producción sin
comparar antes todas sus variables con el estado aprobado.

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
3. Usar el nombre `RaSelEcommerce` y seleccionar **Pagos online**, **Tienda
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
4. Revisar también órdenes con el pago **En revisión**, eventos con firma o
   procesamiento fallido, stock liberado y `processing_error`.
5. Si la API o la base fallan, mantener o colocar
   `MP_CHECKOUT_ENABLED=0`, conservar el stock y repetir la conciliación cuando
   el proveedor se recupere. Nunca asumir que no hubo pago.

La próxima mejora operativa prioritaria es crear en Render el Cron Job
`rasel-mp-reconcile`, rama `main`, schedule UTC `*/10 * * * *` y comando
`python backend/manage.py reconcile_mp_payments --batch-size 100`. Debe
incorporarse primero mediante el flujo normal de `bundle_work`, staging, PR y
aprobación; una vez productivo, nunca debe ejecutar código de staging. Render
cobra por tiempo de ejecución con un mínimo de USD 1 mensual por Cron Job al
momento de esta decisión; verificar el precio vigente antes de provisionarlo.
Cuando se incorpore, deberá recibir por separado `DATABASE_URL`, credenciales
MP, ambiente, alertas y Brevo, y probarse manualmente antes de sustituir la
rutina anterior. Hasta entonces no debe agregarse al Blueprint ni asumirse que
la conciliación ocurre sola.

## Salida a producción de Mercado Pago

Estado vigente desde el 16 de agosto de 2026: `rasel_ecommerce_2` usa las
credenciales productivas de la cuenta vendedora activa, con
`MP_ENVIRONMENT=production` y `MP_CHECKOUT_ENABLED=1`. La rotación se validó
con health check `200`, webhook GET `405`, una compra real controlada, una sola
orden pagada, un único descuento de stock, firma válida, procesamiento sin
error y reintegro total sincronizado. El producto y la variante temporales
quedaron inactivos. No registrar aquí el titular, los identificadores de pago
ni los valores de las credenciales.

La conciliación manual intensiva debe mantenerse durante las 48 horas
posteriores a esta activación y luego continuar con la frecuencia diaria
definida en la sección **Conciliación manual de Mercado Pago**, mientras no
exista el Cron Job productivo.

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

## Meta Pixel y Conversions API

El código está preparado pero apagado por defecto. La recepción en Meta y la
asociación con CP_Rasel requieren verificación del responsable con acceso al
Administrador de eventos; no fueron activadas ni verificadas en producción como
parte de la implementación. El ID es `1400536168898337`. Se incluyó `.env.example`
con placeholders solo para Meta: integrar sus variables sin reemplazar ni
publicar el `.env` existente. Nunca poner el token en templates, JS o comandos
que impriman credenciales.

### Activación y prueba controlada

1. Publicar código y migraciones solamente cuando se autorice, siguiendo el
   flujo de ramas. Mantener las dos banderas en `0` inicialmente. Las migraciones
   son aditivas y no generan eventos históricos.
2. En staging, configurar `META_PIXEL_ENABLED=1` y el ID del conjunto. El
   píxel funciona sin token CAPI. Revisar primero en móvil el aviso con aceptar,
   rechazar y preferencias, navegación y recorrido de compra. No responder
   mantiene Meta apagado; rechazar no impide comprar.
3. En Meta, abrir **Administrador de eventos → RaSel - Tienda online → Probar
   eventos**. Confirmar acceso del operador y asociación con CP_Rasel. Abrir la
   URL de staging desde la herramienta de pruebas, aceptar en un navegador sin
   bloqueadores y recorrer inicio, ficha, agregado al carrito y checkout.
   Verificar PageView, ViewContent, AddToCart e InitiateCheckout de navegador.
   Recargar carrito/checkout no debe repetir sus acciones. No agregar reglas de
   eventos automáticos para estos mismos disparadores en Meta.
4. Para Purchase, generar en Meta un token válido para ese conjunto y cargarlo
   exclusivamente en el backend de staging. Configurar `META_CAPI_ENABLED=1`,
   versión `v26.0` y el código mostrado en **Probar eventos**. Crear un pedido
   nuevo de prueba con aceptación; los pedidos históricos no sirven para esta
   verificación. Confirmar el cobro offline desde el admin o usar el pago MP de
   prueba y su verificación habitual. No realizar compras reales como prueba
   sin informar y acordar esa operación.
5. Consultar primero la cola, sin enviar:

   ```powershell
   python backend/manage.py send_meta_events
   ```

6. Enviar únicamente la orden nueva controlada:

   ```powershell
   python backend/manage.py send_meta_events --send --order <ID>
   ```

   Verificar un único Purchase de servidor con ARS y total del pedido después
   de descuentos, incluido solo el envío cobrado por RaSel. `contents.item_price`
   conserva el precio unitario histórico antes del descuento por medio de pago;
   `value` conserva el total efectivamente cobrado. El admin informa
   estado e intentos; **Recibido por Meta** significa recepción confirmada por
   la API, no garantiza atribución a un anuncio. No hay Purchase de navegador.
7. Quitar `META_TEST_EVENT_CODE` antes de activar producción. Los eventos guardan
   el código y destino original: el comando no transforma pruebas pendientes
   en conversiones productivas ni envía al cambiar el ID. El diagnóstico
   `destination_or_test_mode_mismatch` identifica este bloqueo. Pruebas locales
   automatizadas simulan el proveedor; no cargan ni envían al conjunto real.
8. Validar la recepción antes de autorizar promoción y deploy productivos. No
   habilitar flags ni completar secretos en producción desde un agente como
   parte de un cambio no desplegado. Mantener la aprobación humana del SHA.

La Graph API se consulta mediante HTTPS con `requests`, sin instalar SDK. La
versión inicial fue contrastada con la
[configuración oficial de Meta](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/apiconfig.py).
Referencias de contrato:
[eventos de servidor](https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/server-event/),
[datos de cliente](https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters/)
y [solicitud/código de prueba en el SDK oficial](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/serverside/event_request.py).
Revisar soporte de la versión durante el mantenimiento de la integración.

### Rutina manual, incidentes y conservación

- No existe cron ni worker Meta. Ejecutar el envío después de confirmar cobros
  offline y revisar la cola al menos cada hora durante la operación comercial:

  ```powershell
  python backend/manage.py send_meta_events --send --limit 100
  ```

- `--send` autoriza envío y limpieza. Sin esa opción el comando no escribe ni
  envía. Incluso con envío desactivado, `--send` ejecuta la limpieza. Si falta
  token o la configuración no es válida, lo informa y conserva pendientes.
  Sin ejecutar el comando no hay envío ni reintentos automáticos.
- Timeouts, HTTP 429/5xx y errores transitorios vuelven a pendientes con espera
  de 1, 2, 4, 8 minutos y hasta una hora. Cada nueva ejecución respeta esa fecha.
  Los reclamos vencen a los cinco minutos para recuperar procesos interrumpidos.
  Todos los intentos conservan ID, fecha, importe y payload. Meta puede recibir
  nuevamente el mismo ID si una respuesta se pierde; no se promete exactamente
  una solicitud HTTP, sino una compra lógica con el mismo identificador.
- El plazo es 24 horas desde la creación del evento, con fecha de aprobación de
  máximo siete días para el envío. Al vencer no se cambia la fecha ni se crea
  otra compra. Credenciales/payloads rechazados quedan en **Revisar**. Corregir
  la causa y, mientras siga dentro del plazo y con consentimiento vigente,
  reintentar explícitamente una orden:

  ```powershell
  python backend/manage.py send_meta_events --send --retry-failed --order <ID>
  ```

- Los diagnósticos no guardan mensajes arbitrarios de Meta ni datos personales.
  El admin permite leer estado, intentos, diagnóstico y primera fecha de pago;
  no permite editar eventos. Pago, stock y notificaciones comerciales no
  dependen de la respuesta de Meta.
- Rechazar cancela pendientes, reclamos y errores asociados a la elección;
  reaceptar no los reactiva. Una solicitud que ya estaba en curso no puede
  retirarse. El consentimiento también se comprueba antes de cada envío.
- Contextos de órdenes/borradores y payloads duran 90 días; recibos de acciones
  de navegador, 90 días; auditoría mínima, doce meses. El comando limpia por
  fecha y puede demorarse hasta su próxima ejecución. La primera fecha de pago
  y UUID web permanecen en la orden; no se reconstruyen compras al limpiar.
- La integración omite IP del servidor hasta verificar la cadena real de
  Cloudflare/Render. No habilitar lectura directa de `X-Forwarded-For` o
  `CF-Connecting-IP`; obtener IP exige verificar también el acceso directo al
  origen y los proxies que sobrescriben encabezados.
- Para pausar Meta poner las banderas en `0`. No afecta Mercado Pago ni la
  analítica propia. Para pausar solo CAPI usar `META_CAPI_ENABLED=0`; no borrar
  eventos ni redatar compras al reactivarla. El píxel y los envíos de servidor
  comparten la misma elección de consentimiento.

## Despliegue y rollback

Los pushes a `bundle_work` despliegan automáticamente el servicio de staging.
El servicio productivo `rasel_ecommerce_2` está vinculado a `main` y mantiene
**Auto-Deploy desactivado**, configuración verificada el 16 de agosto de 2026.
No cambiar la rama productiva a `bundle_work` ni activar Auto-Deploy. Antes de
cada publicación, volver a comprobar ambos valores en **Settings → Build &
Deploy**; cualquier diferencia bloquea el despliegue hasta restaurar esta
política.

1. Confirmar en Render que staging sigue vinculado a `bundle_work` con deploy
   automático y producción a `main` con Auto-Deploy apagado.
2. Esperar que staging quede `Live` y revisar allí el cambio en escritorio y
   móvil.
3. Aprobar personalmente el Environment del último SHA y abrir o actualizar el
   PR `bundle_work` → `main` después de que pasen `owner-approval`,
   `app-version` y `promotion-gate`; usar solo **Create a merge commit**.
4. Confirmar que el SHA y `app_version` de `main` coinciden con el PR aprobado.
5. Avanzar `bundle_work` por fast-forward mediante el procedimiento post-merge
   y comprobar que su job `app-version` quede verde.
6. Obtener la aprobación explícita del responsable del sitio para desplegar.
7. En `rasel_ecommerce_2`, usar **Manual Deploy → Deploy latest commit** y
   comprobar que el commit coincida con el aprobado en `main`.
8. Render ejecuta `bash build.sh`: instala dependencias, corre
   `collectstatic` y aplica migraciones.
9. Render ejecuta `bash start.sh`: entra en `backend/` y arranca Gunicorn con
   dos workers.
10. Confirmar `https://rasel.ar/healthz`, home, catálogo, una imagen de R2 y un
   checkout sin completar una compra real. Entrar al admin y comprobar que la
   versión mostrada coincide con `app_version` del commit desplegado.
11. Revisar logs de Render por errores de inicio, base de datos, R2 o Brevo y
    volver a comprobar que Auto-Deploy continúa apagado.

Si un deploy rompe producción, usar el rollback de Render al deploy estable
anterior. No revertir migraciones ni borrar datos sin preparar primero una
recuperación de Neon.

## Operación diaria desde admin

### Reportes y medición de visitas

Abrir **Ver reportes de visitas y compras** desde el inicio del admin. Los
roles Operador y Solo lectura tienen permiso de consulta, sin edición ni
acceso a registros individuales de analítica. Las migraciones sincronizan ese
permiso. El panel separa visitas/etapas de las ventas cobradas y explica sus
fechas y límites.

La medición está activa por defecto. El interruptor de entorno
`ANALYTICS_ENABLED=0` pausa nuevos registros; el panel y las ventas siguen
disponibles. Usar `1` para reanudar. Configurar cada entorno por separado;
staging y producción conservan sus propias bases. No se requieren servicios,
credenciales externas, Redis, workers ni Cron Jobs nuevos.

Para identificar campañas, compartir enlaces como
`https://rasel.ar/?utm_source=instagram&utm_medium=social&utm_campaign=septiembre`.
Usar solo etiquetas de campaña sin datos personales; las etiquetas admiten
letras latinas sin acento, números, guiones y guiones bajos, hasta 64 caracteres.
WhatsApp puede no enviar referencia: etiquetar sus enlaces para distinguirlo
del tráfico directo. La fuente se fija al inicio de cada visita.

La atribución de compras es independiente del origen de entrada: conserva el
último contacto externo durante 30 días mediante una cookie propia firmada.
Volver directamente no renueva el plazo. El checkout guarda un snapshot opcional
que acompaña al borrador de Mercado Pago y a la orden; los pagos tardíos y
reintentos conservan la procedencia original. La tabla atribuye únicamente pedidos
cobrados según el estado financiero actual y reconcilia con las tarjetas de ventas.
**Sin atribución** no equivale a tráfico directo. No completar manualmente
atribuciones de pedidos viejos ni inferir conversión dividiendo ventas por visitas.

El bloque de calidad informa la fecha inicial de la nueva metodología y separa
visitas filtradas, visitas con actividad y solicitudes descartadas por motivo.
No borrar ni descontar el histórico previo. Los dispositivos desconocidos no
son automáticamente bots. Los contadores de descartes solo cubren páginas
públicas exitosas: `/healthz`, administración, archivos y errores están fuera.
El endpoint `/analytics/activity/` es POST con CSRF y token firmado por página;
ignora señales de visitas vencidas y no prolonga sesiones. Su falla no debe
impedir navegar o comprar. El interruptor de medición también pausa señales,
descartes y nuevas atribuciones, conservando snapshots existentes para pagos pendientes.

Antes de publicar, verificar en Render y UptimeRobot que el monitoreo apunte a
`/healthz`. La revisión del 16/09/2026 no pudo verificar sus paneles por falta
de sesión autenticada; el código excluye esa ruta y los agentes reconocibles,
pero esto no certifica la configuración operativa. Mantener esta comprobación
pendiente hasta acceder a los paneles; no afirmar que los contadores son personas.

La limpieza automática intenta un lote como máximo por minuto al llegar
actividad medible, con exclusión mutua en la base entre workers. Elimina hasta
100 filas por tabla: visitas iniciadas hace más de 90 días, sesiones Django ya
vencidas y resúmenes (incluidos descartes) anteriores al mes actual y sus 11 meses previos.
También vacía por lotes los metadatos de atribución vencidos en órdenes y
borradores, sin alterar sus datos comerciales. Nunca
elimina pedidos ni sesiones vigentes. Sin tráfico, la limpieza espera a la
próxima visita; con acumulación se completa en lotes sucesivos.

Para adelantar el mantenimiento o ejecutarlo con la medición pausada:

```powershell
python backend/manage.py cleanup_analytics --batch-size 100 --max-batches 10
```

Los límites admiten de 1 a 1000. Repetir el comando si informa eliminaciones
y todavía existe acumulación. Registrar solo cantidades y tiempos, nunca
contenido de sesiones ni identificadores. Las advertencias de los loggers de
analítica indican fallas del registro sin incluir payloads ni datos del cliente.
Revisar errores, consumo de Neon y latencia después de publicar una campaña;
el almacenamiento está acotado por retención y por combinaciones de fuentes,
pero no hay un cupo garantizado de tráfico gratuito.

El check `promotion-gate` ejecuta la suite, incluida analítica, contra un
PostgreSQL efímero de CI para validar concurrencia real. Las pruebas locales
con SQLite omiten los casos que requieren bloqueos de fila. Antes de promover,
validar filtros y recorrido primero en mobile, luego escritorio, y comparar la
latencia de visitas iniciales y repetidas con la medición pausada en una base
aislada; no usar el tráfico de staff, que se excluye automáticamente.

Limitación previa del checkout MP: ante un primer error HTTP 503 al crear la
preferencia, Django no persiste las modificaciones de sesión de esa respuesta.
El borrador queda reservado, pero el reintento puede responder 403 si la sesión
no conservó ese borrador. No interpretar ese checkout enviado como pago; aplicar
la conciliación habitual a la reserva. El módulo de reportes no cambia ese flujo.

### Catálogo y stock

1. Crear o editar el producto y sus variantes.
2. Mantener precio de venta, SKU, stock, estado activo y relación de packs
   correctos. El precio de venta es siempre el importe base que cobran carrito,
   checkout y Mercado Pago.
3. Para comunicar una campaña, completar juntos **precio regular (ARS)** y
   **texto de promoción** en cada presentación. El precio debe ser una referencia
   verdadera y mayor al precio de venta; el texto admite hasta 40 caracteres y
   se presenta visualmente en mayúsculas debajo de **Precio de lista** (por
   ejemplo, cargar “Lanzamiento web” o “Black Friday”). El admin conserva el
   texto escrito y rechaza los campos incompletos o un precio regular igual o
   menor al cobrado.
4. Confirmar en inicio, tienda, recomendados, detalle y compra rápida que la
   leyenda, el precio tachado y el primer porcentaje corresponden a la misma
   presentación. La burbuja **X% OFF ADICIONAL** pertenece a la configuración
   comercial global y permanece visible en productos sin campaña mientras el
   descuento offline sea mayor a cero. Al terminar la campaña, colocar el
   importe definitivo como precio de venta y vaciar juntos el precio regular y
   el texto. No queda un historial ni hay cambio automático por fecha.
5. Como staging y producción usan bases separadas, cargar, cambiar o retirar estos
   valores en cada admin después del despliegue correspondiente.
6. Cargar o reemplazar imágenes; confirmar que la URL generada usa R2 y que la
   imagen se ve en listado y detalle público.

### Envíos y retiros

1. Editar zonas, precios, mínimos, reglas de código postal y efectivo permitido
   desde el admin.
2. Mantener exactamente una zona por defecto activa.
3. Editar puntos de retiro activos, dirección e indicaciones antes de ofrecerlos
   al cliente.

### Campañas de envío gratis en CABA

1. Antes de publicar, verificar tarifas y cobertura reales: CABA comparte zona
   con Moreno. No cambiar esa zona para activar una campaña. Mantener la zona
   por defecto y el reparto propio de CABA correctamente configurados.
2. Abrir **Envíos → Promociones de envío → Añadir**. Preparar título,
   introducción, inicio y fin en horario argentino con **Habilitada** apagada.
   Para una semana, configurar siete días corridos. El instante final es
   exclusivo: por ejemplo, cerrar un lunes a las 00:00 excluye ese lunes.
3. Revisar los datos antes de habilitar: publicar crea el enlace permanente y
   bloquea fechas y textos. Operador puede crear y cambiar habilitación; Solo
   lectura consulta. No se permite borrar ni superponer campañas habilitadas.
   Para nuevas fechas o condiciones, crear otra campaña.
4. Configurar staging y producción por separado. En staging usar solamente
   datos ficticios y probar comienzo, vencimiento, suspensión, cotización,
   reconfirmación y compras con envío/retiro. Antes de difundir, comprobar en
   producción la versión aprobada, el enlace, stock y cobertura de CABA.
5. Comprobar en Cloudflare que ninguna regla sobrescriba `Cache-Control` ni
   guarde HTML comercial, `/shipping/quote/` o `/shipping/promotion-status/`.
   Purgar HTML comercial previamente cacheado si existe. El vencimiento no
   necesita desplegar código ni restaurar tarifas manualmente.
6. Difundir la URL publicada con UTM solamente en canales externos, por ejemplo
   `utm_source=instagram&utm_medium=social&utm_campaign=envio_caba_octubre`.
   Revisar al iniciar y terminar que banner y cotización coincidan con el estado
   del admin. Durante la campaña controlar pedidos, errores, stock y la rutina
   habitual de conciliación MP.
7. Filtrar pedidos y borradores por campaña. **Envío habitual (histórico)** y
   ahorro adicional permiten distinguir pedidos beneficiados de descuentos
   nuevos: compras que ya tenían envío gratis tienen ahorro adicional cero.
   Los snapshots no se editan y los pedidos aceptados mantienen el costo incluso
   si se suspende o termina la campaña. No recalcularlos con tarifas nuevas.
8. Para suspender nuevas aplicaciones, deshabilitar. La página conserva sus
   condiciones y la franja muestra suspensión hasta el cierre previsto. Si se
   anunció fuera del sitio, comunicar la suspensión en esos mismos canales;
   esta comunicación es responsabilidad del operador, no automática.
9. Si vence mientras el comprador completa el checkout, debe revisar y
   confirmar el nuevo total; ese primer POST no reserva stock ni genera pago.
   Reservas MP válidas conservan su beneficio original. La limitación previa
   de sesión/reintento tras un 503 inicial de Mercado Pago continúa pendiente
   y requiere la conciliación habitual; la campaña no la corrige.

### Descuento por efectivo y transferencia

1. Abrir **Catálogo → Configuración comercial → Descuento por medios de
   pago** y editar **Descuento por efectivo/transferencia (%)**. Admite enteros
   entre 0 y 50; el valor inicial es 10.
2. Guardar y comprobar en una ficha de producto, compra rápida, checkout y
   Términos que el importe y todos los textos muestran el nuevo porcentaje. En
   las vidrieras aparece como **X% OFF ADICIONAL**; el importe continúa redondeándose
   hacia abajo al múltiplo de $50, por lo que el ahorro efectivo puede ser mayor.
   Staging y producción tienen bases separadas y deben configurarse por separado.
3. Usar 0 para desactivar el beneficio: no se aplica el redondeo a $50 ni se
   muestran precios o leyendas de descuento. Transferencia y efectivo siguen
   disponibles con el precio de venta completo.
4. El cambio afecta cotizaciones y pedidos nuevos de inmediato. Cada orden ya
   creada conserva el porcentaje y el importe aplicados; nunca recalcularla con
   el valor actual del admin.

### Pedidos

1. Toda orden nueva tiene la entrega **Pendiente**. Transferencia y efectivo
   comienzan con el pago **Pendiente**; Mercado Pago queda **Aprobado** o **En
   revisión** según la respuesta validada de la API.
2. Las órdenes por transferencia o efectivo muestran el descuento que
   quedó guardado al crearlas. El precio promocional se calcula por variante,
   redondeando hacia abajo al múltiplo de $50, y luego se multiplica por la
   cantidad. Revisar `descuento por medio de pago`, subtotal, envío y total antes
   de cobrar o confirmar; Mercado Pago debe mostrar descuento cero. El envío
   nunca forma parte de la base promocional.
3. Para transferencia, verificar el comprobante de WhatsApp y usar **Confirmar
   pago**. Nunca confirmar manualmente un pago de Mercado Pago.
4. Usar **Despachar / dejar listo para retirar** cuando el pedido sale o queda
   disponible. Transferencia y Mercado Pago requieren pago aprobado; efectivo
   contraentrega puede avanzar con el cobro pendiente.
5. Al confirmar la recepción, usar **Marcar como entregado / retirado**. Para
   registrar simultáneamente un cobro offline y la entrega, usar **Cobrar y
   completar**; esta acción envía un único correo final. En Mercado Pago solo
   completa si la API ya aprobó el pago.
6. Leer siempre las columnas **Situación**, **Pago** y **Entrega**; los estados
   no se editan manualmente y los botones disponibles dependen del estado real.
7. En una orden MP aprobada, reintegrar primero en Mercado Pago; cancelar en
   RaSel no mueve dinero. No restaurar stock despachado o completado sin
   devolución física confirmada.

Antes de aprobar un despliegue, probar en staging una compra con envío y otra
con retiro: al alternar Mercado Pago, transferencia y efectivo, el resumen debe
mostrar u ocultar el descuento sin recargar la página. Al confirmar, el total de
la orden y del email debe coincidir con el resumen. La tasa mínima se administra
desde **Configuración comercial**; el múltiplo de redondeo de $50 sigue
versionado en `config/pricing.py` y cambiarlo requiere código, pruebas,
actualización de la comunicación visible y el flujo staging → aprobación →
producción.

## Incidentes frecuentes

| Síntoma | Comprobación y acción |
| --- | --- |
| Sitio lento o dormido | Confirmar que UptimeRobot consulta `/healthz`; revisar estado y logs de Render. |
| Sitio responde pero falla checkout | Revisar logs de Render y la conexión `DATABASE_URL` a Neon. `/healthz` no prueba la base. |
| Imagen faltante | Confirmar el producto en admin, las variables R2 y la existencia del objeto en el bucket; no asumir que `MEDIA_ROOT` local la recuperará. |
| No llega un email | Revisar `BREVO_API_KEY`, remitente verificado, destinatario y registros de Brevo; buscar la excepción en Render. |
| Stock incorrecto | Revisar ítems y estado de la orden; cancelar desde admin restaura stock una vez. |
| Pago aprobado sin orden normal | Buscar el borrador y evento, ejecutar **Reconciliar con Mercado Pago** y revisar las órdenes con pago **En revisión**; no prometer entrega ni cobrar de nuevo. |
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

- Confirmar que el trabajo parte de `bundle_work`, no de `main`.
- Incrementar `app_version` en cada commit según SemVer.
- Confirmar qué servicios externos y variables toca el cambio.
- Ejecutar tests y verificaciones relevantes en el entorno Conda.
- Publicar primero en staging y validar allí el flujo público afectado.
- Promover mediante PR, `owner-approval`, checks verdes y **Create a merge
  commit**.
- Avanzar `bundle_work` por fast-forward hasta el mismo SHA de `main` y verificar
  `app-version`.
- Desplegar producción manualmente desde el SHA aprobado de `main`.
- Actualizar `CURRENT_SYSTEM.md` y/o este documento según `AGENTS.md`.
- Registrar el cambio en `CHANGELOG.md` si modifica comportamiento u operación.
