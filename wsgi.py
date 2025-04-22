import os
import sys
import threading
import asyncio
import time
from server import app, start_websocket_server_thread, init_data_directories

# Initialize data directories
init_data_directories()

# Start WebSocket server in a separate thread when using WSGI server
if os.environ.get('RUNNING_IN_PRODUCTION', 'False').lower() == 'true':
    websocket_thread = threading.Thread(target=start_websocket_server_thread, daemon=True)
    websocket_thread.start()
    
    # Give the WebSocket server time to start
    time.sleep(2)
    print("WebSocket server thread started in production mode")

# Gunicorn WSGI application entry point
if __name__ == "__main__":
    app.run() 