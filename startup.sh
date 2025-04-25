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

# Start the Flask application with gunicorn
# Reduced websocket timeout, increased ping/pong frequency, added worker connection timeout
export WS_PING_INTERVAL=10
export WS_PING_TIMEOUT=5
export WS_CLOSE_TIMEOUT=5

gunicorn --bind=0.0.0.0:5000 --worker-class=eventlet -w 1 --timeout 120 --keep-alive 65 --log-level=debug server:app 