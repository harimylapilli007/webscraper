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
gunicorn --bind=0.0.0.0:8000 --worker-class=eventlet -w 1 server:app 