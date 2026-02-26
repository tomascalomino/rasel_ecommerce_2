# Setup local

## Activar entorno
conda activate rasel-ecomm_venv

## Instalar deps
pip install -r requirements.txt

## Variables de entorno
Copiar `.env.example` a `.env` (NO se commitea) y completar valores.

## Correr
cd backend
python manage.py migrate
python manage.py runserver

## Variables de entorno (local)
- MP_ACCESS_TOKEN=... (MercadoPago, sandbox o prod)

## Cart global en templates
Se usa un context processor: `cart.context_processors.cart` para acceder a `cart` desde cualquier template.
