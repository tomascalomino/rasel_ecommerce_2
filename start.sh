#!/usr/bin/env bash
set -o errexit

# Ensure we run inside the backend folder where manage.py lives
cd backend

# Run migrations against the configured DATABASE_URL
python manage.py migrate --noinput

# Start gunicorn (exec to replace the shell process)
exec gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 60
