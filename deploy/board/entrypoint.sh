#!/bin/sh
set -e

python manage.py makemigrations posts --noinput
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed

exec gunicorn board.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile -
