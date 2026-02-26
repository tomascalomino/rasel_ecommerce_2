# Setup local

## Activar entorno
conda activate rasel-ecomm_venv

## Instalar deps
pip install -r requirements.txt

## Variables de entorno
Crear archivo `.env` (NO se commitea) y completar valores.

Ejemplo mínimo:
- `SECRET_KEY=...`
- `DEBUG=1`
- `ALLOWED_HOSTS=127.0.0.1,localhost`
- `SITE_URL=http://127.0.0.1:8000`
- `MP_ACCESS_TOKEN=...`

## Correr
cd backend
python manage.py migrate
python manage.py runserver

## Variables de entorno (local)
- MP_ACCESS_TOKEN=... (MercadoPago, sandbox o prod)

## Cart global en templates
Se usa un context processor: `cart.context_processors.cart` para acceder a `cart` desde cualquier template.
