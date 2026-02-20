#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python backend/manage.py collectstatic --no-input
python backend/manage.py migrate
