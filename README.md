# RaSel

Tienda online de aceite de oliva. Producción: [rasel.ar](https://rasel.ar).

RaSel está construida con Django y PostgreSQL, se despliega en Render y usa
Cloudflare para DNS, proxy e imágenes en R2. El checkout ofrece transferencia y
efectivo. Mercado Pago Checkout Pro está implementado con reservas, webhooks y
conciliación, pero queda oculto por defecto hasta completar la configuración
externa y habilitar `MP_CHECKOUT_ENABLED`.

## Empezar aquí

- Agentes: leer y seguir [AGENTS.md](AGENTS.md).
- Funcionamiento actual: [docs/CURRENT_SYSTEM.md](docs/CURRENT_SYSTEM.md).
- Operación, variables y despliegue: [docs/OPERATIONS.md](docs/OPERATIONS.md).
- Historial de cambios aplicados: [docs/CHANGELOG.md](docs/CHANGELOG.md).

## Desarrollo local

```powershell
conda activate rasel_ecommerce_venv
pip install -r requirements.txt
python backend/manage.py migrate
python backend/manage.py runserver
```

Crear `.env` en la raíz con las variables necesarias; consultar el inventario
sin secretos en `docs/OPERATIONS.md`.
