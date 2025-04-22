FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gevent gevent-websocket gunicorn

COPY . .

EXPOSE 5000 6789

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--worker-class", "geventwebsocket.gunicorn.workers.GeventWebSocketWorker", "--workers", "1", "server:app"]