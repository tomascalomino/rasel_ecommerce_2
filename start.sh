#!/usr/bin/env bash
set -o errexit

# Ensure we run inside the backend folder where manage.py lives
cd backend

# Run migrations against the configured DATABASE_URL
python manage.py migrate --noinput

# Load initial fixture once (if provided) to restore products.
# We create a sentinel file in the repo root to avoid reloading on restarts.
if [ -f fixtures/shop.json ] && [ ! -f ../.fixtures_loaded ]; then
	echo "Found fixtures/shop.json — loading initial data..."
	python manage.py loaddata fixtures/shop.json || true
	touch ../.fixtures_loaded
fi

# Start gunicorn (exec to replace the shell process)
exec gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 60
