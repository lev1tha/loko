"""Gunicorn config for the Loko ERP Django backend (production).

Run:  gunicorn -c gunicorn.conf.py loko.wsgi:application
Binds to localhost only — Cloudflare Tunnel forwards traffic to it.
"""

import multiprocessing

bind = "127.0.0.1:8000"
workers = max(2, multiprocessing.cpu_count() * 2 + 1)
threads = 2
timeout = 60
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
loglevel = "info"
# Trust the X-Forwarded-* headers coming from Cloudflare Tunnel.
forwarded_allow_ips = "127.0.0.1"
