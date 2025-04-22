FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gevent gevent-websocket gunicorn flask-socketio

COPY . .

# Create necessary directories
RUN mkdir -p /app/data/user_configs /app/output /app/logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV GUNICORN_CMD_ARGS="--access-logfile=- --error-logfile=- --capture-output --enable-stdio-inheritance"
ENV WS_PING_INTERVAL=30
ENV WS_PING_TIMEOUT=10
ENV WS_CLOSE_TIMEOUT=10
ENV ALLOWED_ORIGINS="*"
ENV DEBUG=False

EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Run with production settings
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--worker-class", "geventwebsocket.gunicorn.workers.GeventWebSocketWorker", \
     "--workers", "4", \
     "--threads", "2", \
     "--timeout", "120", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "50", \
     "--log-level", "info", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--forwarded-allow-ips", "*", \
     "--proxy-protocol", \
     "server:app"]