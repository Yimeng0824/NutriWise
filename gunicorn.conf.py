import os

bind = os.getenv('GUNICORN_BIND', '0.0.0.0:8080')
workers = 1  # Each extra worker duplicates BGE memory; this targets a 4 GB host.
worker_class = 'gthread'
threads = 4
timeout = 180
graceful_timeout = 30
keepalive = 5
preload_app = False
accesslog = '-'
errorlog = '-'
loglevel = 'info'
access_log_format = '%(h)s %(m)s %(U)s %(s)s %(L)s'
