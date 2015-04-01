#!/bin/bash -x

rabbitmq-server &
sleep 10
cd /app
su - daemon -s /bin/bash -c 'cd /app; celery -A UploadServer worker --loglevel=info' &
su - daemon -s /bin/bash -c 'cd /app; python manage.py runserver 0.0.0.0:8000'
