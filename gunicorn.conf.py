import os
import multiprocessing

# Configure Gunicorn for Azure App Service
bind = "0.0.0.0:" + os.environ.get("PORT", "8000")

# Worker configuration
workers = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "sync"
worker_connections = 1000
timeout = 120
keepalive = 60

# Production settings
preload_app = True
daemon = False
reload = False
spew = False

# Logging configuration
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# Set environment variables
raw_env = [
    "RUNNING_IN_PRODUCTION=true"
]

# Automatically exit workers after handling a certain number of requests
max_requests = 10000
max_requests_jitter = 1000 