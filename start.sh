#!/usr/bin/env bash
set -o errexit

# Ensure we run inside the backend folder where manage.py lives
cd backend

# Run migrations against the configured DATABASE_URL
python manage.py migrate --noinput

# Load initial fixture once (if provided) to restore products.
# We create a sentinel file in the repo root to avoid reloading on restarts.
if [ -f fixtures/shop.json ] && ( [ ! -f ../.fixtures_loaded ] || [ "$LOAD_FIXTURES" = "1" ] ); then
	echo "Found fixtures/shop.json — loading initial data..."
	python manage.py loaddata fixtures/shop.json || true
	# mark as loaded unless explicit reload requested
	if [ "$LOAD_FIXTURES" != "1" ]; then
		touch ../.fixtures_loaded
	else
		echo "LOAD_FIXTURES=1 was set — fixture loaded but sentinel not created (one-time run)"
	fi
fi

# Optionally create an admin user from environment variables (one-time)
if [ "$CREATE_ADMIN" = "1" ]; then
  echo "CREATE_ADMIN=1 detected — ensuring admin user exists..."
  python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model
User = get_user_model()
u = os.environ.get('ADMIN_USERNAME')
e = os.environ.get('ADMIN_EMAIL')
p = os.environ.get('ADMIN_PASSWORD')
if not u or not p:
	print('ADMIN_USERNAME or ADMIN_PASSWORD not set — skipping')
else:
	if User.objects.filter(username=u).exists():
		print('Admin user already exists:', u)
	else:
		User.objects.create_superuser(u, e or '', p)
		print('Created admin user:', u)
PY
fi

# Start gunicorn (exec to replace the shell process)
exec gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 60
