release: python manage.py migrate --noinput
web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
worker: celery -A config.celery_app worker -l INFO --concurrency=2 --max-tasks-per-child=100
beat: celery -A config.celery_app beat -l INFO
