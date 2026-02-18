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
