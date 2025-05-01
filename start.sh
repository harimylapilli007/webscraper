#!/bin/bash

# Start Xvfb
Xvfb :99 -screen 0 1024x768x24 > /dev/null 2>&1 &

# Wait for Xvfb to start
sleep 2

# Run the application
exec gunicorn server:app --bind 0.0.0.0:5000 