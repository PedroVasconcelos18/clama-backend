web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
worker: celery -A config.celery_app worker -l INFO
beat: celery -A config.celery_app beat -l INFO
