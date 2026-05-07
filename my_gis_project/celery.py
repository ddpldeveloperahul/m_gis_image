import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web_gis.settings')

app = Celery('web_gis')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()