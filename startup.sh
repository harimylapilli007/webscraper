#!/bin/bash

# Navigate to the application directory
cd /home/site/wwwroot

# Make sure the script is executable
chmod +x startup.sh

# Install dependencies if not already installed
pip install -r requirements.txt

# Ensure Azure environment variables are set
export RUNNING_IN_PRODUCTION=true
export PORT=${PORT:-8000}
export HOST=${HOST:-0.0.0.0}
export WEBSOCKET_HOST=${WEBSOCKET_HOST:-0.0.0.0}

# Start the application using Gunicorn with our config
gunicorn -c gunicorn.conf.py wsgi:app 