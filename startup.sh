#!/bin/bash

# Install dependencies
pip install -r requirements.txt

# Set Python path to include the current directory
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Start the server with Gunicorn
gunicorn --worker-class gevent --bind 0.0.0.0:8000 server:app 