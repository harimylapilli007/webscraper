#!/bin/bash

# Create a virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create necessary directories
mkdir -p data
mkdir -p output
mkdir -p logs

# Set environment variables for better logging
export PYTHONUNBUFFERED=1
export FLASK_DEBUG=1
export FLASK_ENV=development

# More conservative websocket settings
export WS_PING_INTERVAL=25
export WS_PING_TIMEOUT=20
export WS_CLOSE_TIMEOUT=15
export EVENTLET_NO_GREENDNS=yes  # Prevent DNS resolution issues
export EVENTLET_WSGI_MULTIPROCESS=0  # Disable multiprocessing
export EVENTLET_WSGI_MULTITHREAD=1  # Enable multithreading

# Start with eventlet worker and better logging
gunicorn --bind=0.0.0.0:5000 \
         --worker-class=eventlet \
         -w 1 \
         --timeout 300 \
         --keep-alive 120 \
         --log-level=debug \
         --access-logfile logs/access.log \
         --error-logfile logs/error.log \
         --capture-output \
         --enable-stdio-inheritance \
         --access-logfile - \
         --error-logfile - \
         server:app 