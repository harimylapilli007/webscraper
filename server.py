from flask import Flask, jsonify, request, send_file
import subprocess
import threading
import asyncio
import signal
import sys
from flask_cors import CORS
import websockets
import queue
import json
import os
import uuid
from datetime import datetime
import time
import logging
from dotenv import load_dotenv
from flask_socketio import SocketIO, emit, join_room, leave_room
import socket

# Load environment variables from .env file
load_dotenv()

# Initialize event loop
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Get configuration from environment
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
PORT = int(os.environ.get('PORT', 5000))  # Changed to 8000 to match Azure default
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'https://webscraper-frontend-b3gmeeckhue2b3fz.canadacentral-01.azurewebsites.net')

# Azure-specific configurations
AZURE_WEBSITE_HOSTNAME = os.environ.get('WEBSITE_HOSTNAME', '')
AZURE_WEBSITE_SITE_NAME = os.environ.get('WEBSITE_SITE_NAME', '')
IS_AZURE = bool(AZURE_WEBSITE_HOSTNAME)

# Adjust WebSocket configuration for Azure
WS_PING_INTERVAL = int(os.environ.get('WS_PING_INTERVAL', 30))  # Increased from 25
WS_PING_TIMEOUT = int(os.environ.get('WS_PING_TIMEOUT', 25))   # Increased from 20
WS_CLOSE_TIMEOUT = int(os.environ.get('WS_CLOSE_TIMEOUT', 25)) # Increased from 20
WS_HOST = os.environ.get('WS_HOST', '0.0.0.0')
WS_PORT = int(os.environ.get('WS_PORT', PORT))

# Add WebSocket connection retry settings
WS_RECONNECT_ATTEMPTS = 10
WS_RECONNECT_DELAY = 2
WS_RECONNECT_DELAY_MAX = 30

# Adjust allowed origins for Azure
if IS_AZURE:
    ALLOWED_ORIGINS = [
        f'https://{AZURE_WEBSITE_HOSTNAME}',
        f'http://{AZURE_WEBSITE_HOSTNAME}',
        'http://localhost:3000',
        'https://webscraper-frontend-b3gmeeckhue2b3fz.canadacentral-01.azurewebsites.net'
    ]
else:
    ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*').split(',')

def find_available_port(start_port):
    port = start_port
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('', port))
            sock.close()
            return port
        except OSError:
            port += 1

async def websocket_handler(websocket):
    user_id = None
    client_info = "unknown"
    try:
        client_info = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"New WebSocket client connected from {client_info}")
        
        # Wait for initial message with user ID
        message = await websocket.recv()
        data = json.loads(message)
        
        if data.get("type") == "init":
            user_id = data.get("user_id")
            if user_id:
                logger.info(f"✅ WEBSOCKET CLIENT REGISTERED - User ID: {user_id}")
                connected_clients[websocket] = user_id
                await websocket.send(json.dumps({
                    "type": "connection",
                    "status": "connected",
                    "user_id": user_id,
                    "message": "Connected successfully"
                }))
    except Exception as e:
        logger.error(f"WebSocket handler error: {e}")
    finally:
        if websocket in connected_clients:
            del connected_clients[websocket]

app = Flask(__name__)

# Initialize SocketIO with Azure-specific settings
logger.info("Initializing Socket.IO with configuration:")
logger.info(f"Ping Interval: {WS_PING_INTERVAL}")
logger.info(f"Ping Timeout: {WS_PING_TIMEOUT}")
logger.info(f"Close Timeout: {WS_CLOSE_TIMEOUT}")

socketio = SocketIO(
    app,
    cors_allowed_origins=ALLOWED_ORIGINS,
    ping_interval=WS_PING_INTERVAL,
    ping_timeout=WS_PING_TIMEOUT,
    logger=True,
    engineio_logger=True,
    transports=['polling', 'websocket'],
    async_mode='threading',
    max_http_buffer_size=1e8,
    async_handlers=True,
    monitor_clients=True,
    allow_upgrades=True,
    cookie=False,
    path='socket.io/',
    ping_interval_grace_period=2000,
    max_retries=WS_RECONNECT_ATTEMPTS,
    reconnection=True,
    reconnection_attempts=WS_RECONNECT_ATTEMPTS,
    reconnection_delay=WS_RECONNECT_DELAY * 1000,
    reconnection_delay_max=WS_RECONNECT_DELAY_MAX * 1000,
    websocket_ping_interval=WS_PING_INTERVAL,
    websocket_ping_timeout=WS_PING_TIMEOUT,
    websocket_max_message_size=10485760,
    websocket_compression=True,
    websocket_per_message_deflate=True
)

# Add error handlers for SocketIO
@socketio.on_error()
def error_handler(e):
    logger.error(f"SocketIO error: {e}")
    
@socketio.on_error_default
def default_error_handler(e):
    logger.error(f"SocketIO default error: {e}")

logger.info("Socket.IO initialized successfully")

# Configure CORS with Azure-specific settings
CORS(app, resources={
    r"/*": {
        "origins": ALLOWED_ORIGINS,
        "methods": ["GET", "POST", "OPTIONS", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "X-User-Id", "Authorization", "Access-Control-Allow-Origin", "Access-Control-Allow-Headers", "Access-Control-Allow-Methods"],
        "supports_credentials": True,
        "max_age": 3600,
        "expose_headers": ["Content-Type", "X-User-Id", "Authorization", "Access-Control-Allow-Origin"],
        "send_wildcard": False,
        "automatic_options": True
    }
})

# Add CORS headers to all responses
@app.after_request
def after_request(response):
    return response

# Store WebSocket clients with user-specific rooms
connected_clients = {}  # Maps client_id to user_id
user_rooms = {}  # Maps user_id to set of client_ids
active_connections = {}  # Maps user_id to active WebSocket connections

# Add request logging middleware
@app.before_request
def log_request_info():
    logger.info(f"Request Method: {request.method}")
    logger.info(f"Request Path: {request.path}")
    logger.info("Request Headers:")
    for header, value in request.headers:
        logger.info(f"  {header}: {value}")
    
    # Debug headers more extensively
    logger.info("DEBUG - Raw Headers Dict:")
    for name, value in request.headers.items():
        logger.info(f"  Raw Header [{name}]: {value}")
    
    # Get and log user ID with more debugging
    user_id = request.headers.get('X-User-Id', 'anonymous')
    logger.info(f"User ID from header: {user_id}")
    
    # Debug additional details
    if user_id == 'anonymous':
        logger.warning("X-User-Id header is missing or anonymous - checking alternate sources")
        # Try other common header naming variations
        alt_header_names = ['x-user-id', 'X-USER-ID', 'x_user_id', 'HTTP_X_USER_ID']
        for header_name in alt_header_names:
            if header_name in request.headers:
                logger.info(f"Found user ID in alternate header {header_name}: {request.headers[header_name]}")
                
        # Check if it might be in request args or form
        if 'userId' in request.args:
            logger.info(f"Found userId in query params: {request.args.get('userId')}")
        if request.is_json and 'user_id' in request.json:
            logger.info(f"Found user_id in JSON body: {request.json.get('user_id')}")

# Initialize data directories and default config
def init_data_directories():
    """Create necessary directories for user configs and output"""
    # Create data directory
    os.makedirs('data', exist_ok=True)
    os.makedirs(os.path.join('data', 'user_configs'), exist_ok=True)
    os.makedirs('output', exist_ok=True)
    logger.info("Initialized data directories")

# Initialize directories when server starts
init_data_directories()

# Job management
class ScraperJob:
    def __init__(self, job_id, user_id):
        self.job_id = job_id
        self.user_id = user_id
        self.process = None
        self.log_queue = queue.Queue()
        self.status = "pending"
        self.start_time = datetime.now()
        self.completion_time = None  # Add completion time tracking
        self.output_dir = f"output/{job_id}"
        self.should_stop = False  # Flag to indicate if the scraper should be stopped
        os.makedirs(self.output_dir, exist_ok=True)
        logger.info(f"Created new job {job_id} for user {user_id}")

# Store active scraping jobs and connected clients with their user IDs
active_jobs = {}

def signal_handler(sig, frame):
    print("Shutting down gracefully...")
    # Force stop all active jobs immediately
    for job in active_jobs.values():
        if job.process:
            try:
                job.process.kill()  # Use kill instead of terminate for immediate stop
                job.process.wait(timeout=0.5)  # Very short timeout
            except:
                pass
            job.process = None
            job.status = "stopped"
    
    # Force cleanup of all output directories
    for job_id, job in list(active_jobs.items()):
        try:
            if os.path.exists(job.output_dir):
                import shutil
                shutil.rmtree(job.output_dir, ignore_errors=True)
        except:
            pass
        del active_jobs[job_id]
    
    # Force exit
    os._exit(0)  # Use os._exit to force immediate termination

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# SocketIO event handlers
@socketio.on('connect')
def handle_connect():
    client_id = request.sid
    
    # Try getting the user ID from various sources
    user_id = None
    
    # Try header first
    user_id = request.headers.get('X-User-Id')
    
    # If not in header, try query params
    if not user_id and 'userId' in request.args:
        user_id = request.args.get('userId')
        logger.info(f"Got user ID from query parameter: {user_id}")
    
    # If still not found, try auth parameter (used by socket.io)
    if not user_id and hasattr(request, 'auth') and request.auth and 'X-User-Id' in request.auth:
        user_id = request.auth['X-User-Id']
        logger.info(f"Got user ID from auth parameter: {user_id}")
        
    logger.info(f"⚡ New client connection attempt - SID: {client_id}")
    
    if not user_id:
        logger.warning(f"❌ No user ID provided for client {client_id}")
        return False  # Reject connection without user ID
    
    try:
        # Store the client ID with user ID
        connected_clients[client_id] = user_id
        
        # Initialize or update user room
        if user_id not in user_rooms:
            user_rooms[user_id] = set()
        user_rooms[user_id].add(client_id)
        
        # Add to active connections
        active_connections[user_id] = request.namespace
        
        logger.info(f"✅ Client connected successfully - User: {user_id} - SID: {client_id}")
        
        # Join user-specific room
        join_room(f"user_{user_id}")
        
        # Send connection confirmation
        emit('connection', {
            'type': 'connection',
            'status': 'connected',
            'message': 'Connected successfully',
            'user_id': user_id,
            'timestamp': datetime.now().isoformat()
        }, room=client_id)
        
        return True
    except Exception as e:
        logger.error(f"❌ Error in connection handler: {str(e)}")
        return False

@socketio.on('disconnect')
def handle_disconnect():
    client_id = request.sid
    try:
        # Get user ID associated with this client
        user_id = connected_clients.get(client_id)
        
        # Remove this client from connected clients
        if client_id in connected_clients:
            del connected_clients[client_id]
        
        # Remove from user's room if applicable
        if user_id and user_id in user_rooms:
            if client_id in user_rooms[user_id]:
                user_rooms[user_id].remove(client_id)
            
            # If user has no more connected clients, clean up user room
            if not user_rooms[user_id]:
                del user_rooms[user_id]
                if user_id in active_connections:
                    del active_connections[user_id]
        
        logger.info(f"Client disconnected - SID: {client_id}, User: {user_id or 'unknown'}")
        
        # Leave user room
        if user_id:
            leave_room(f"user_{user_id}")
            
    except Exception as e:
        logger.error(f"Error in disconnect handler: {str(e)}")
        # Continue even if there's an error to ensure cleanup
    
    # Return True to acknowledge successful disconnection
    return True

@socketio.on('init')
def handle_init(data):
    client_id = request.sid
    user_id = data.get('user_id')
    
    if not user_id:
        logger.warning(f"❌ No user ID provided in init message from {client_id}")
        return
    
    try:
        # Update connected clients mapping
        connected_clients[client_id] = user_id
        
        # Initialize or update user room
        if user_id not in user_rooms:
            user_rooms[user_id] = set()
        user_rooms[user_id].add(client_id)
        
        # Add to active connections
        active_connections[user_id] = request.namespace
        
        # Join user-specific room
        join_room(f"user_{user_id}")
        
        logger.info(f"✅ Client initialized - User: {user_id} - SID: {client_id}")
        
        # Send confirmation to specific client
        emit('connection', {
            'type': 'connection',
            'status': 'initialized',
            'message': 'Connection initialized successfully',
            'user_id': user_id,
            'timestamp': datetime.now().isoformat()
        }, room=client_id)
    except Exception as e:
        logger.error(f"❌ Error in init handler: {str(e)}")

def send_log_to_clients(job_id: str, message: str):
    """Send a log message to all connected clients for a specific job"""
    if not job_id:
        logger.warning("Attempt to send log with no job_id")
        return
        
    try:
        job = active_jobs.get(job_id)
        if not job:
            logger.warning(f"Cannot send log for unknown job {job_id}")
            return
            
        user_id = job.user_id
        if not user_id:
            logger.warning(f"Job {job_id} has no associated user_id")
            return
            
        # Check if user has active connections
        if user_id not in user_rooms or not user_rooms[user_id]:
            logger.info(f"No active clients for user {user_id}, skipping log message")
            return
            
        log_msg = {
            'type': 'log',
            'job_id': job_id,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }
        
        # Filter log messages if needed
        if should_filter_log_message(message):
            return
            
        # Send to room instead of individual clients to avoid connection issues
        try:
            room_name = f"user_{user_id}"
            socketio.emit('log', log_msg, room=room_name, namespace='/')
            logger.debug(f"Log sent to room {room_name}: {message[:50]}...")
        except Exception as e:
            # Just log the error but don't crash
            logger.error(f"Failed to send log to room {room_name}: {str(e)}")
    except Exception as e:
        logger.error(f"Error sending log message: {str(e)}")

def send_state_update(job_id, status):
    """Send a state update to all connected clients for the specific user."""
    try:
        user_id = None
        for job in active_jobs.values():
            if job.job_id == job_id:
                user_id = job.user_id
                break
        
        if not user_id:
            logger.error(f"No user ID found for job {job_id}")
            return
            
        data = {
            'type': 'state',
            'job_id': job_id,
            'status': status,
            'user_id': user_id,
            'timestamp': datetime.now().isoformat()
        }
        
        # Send only to clients in the user's room
        if user_id in user_rooms:
            for client_id in user_rooms[user_id]:
                socketio.emit('state', data, room=client_id)
    except Exception as e:
        logger.error(f"Error sending state update to clients: {str(e)}")

def get_base_config():
    """Get the base configuration structure for new users"""
    return {
        "base_url": "",
        "container_selector": "",
        "fields": {},
        "scroll": False,
        "scroll_wait": 3,
        "initial_wait": 3,
        "paginate": False,
        "start_page": 1,
        "max_pages": 1,
        "next_page_selector": "",
        "page_wait": 2,
        "max_scroll_attempts": 20,
        "load_more_selector": "",
        "load_more_wait": 3,
        "scrape_subpages": False,
        "subpage_wait": 3,
        "subpage_fields": {},
        "output_json": "",
        "output_excel": "",
        "concurrent_settings": {
            "max_concurrent_jobs": 3,
            "base_request_delay": 2,
            "max_concurrent_requests": 2,
            "job_spacing_delay": 3
        }
    }

def get_user_config_path(user_id):
    """Get the path to a user's configuration file"""
    return os.path.join('data', 'user_configs', f'config_{user_id}.json')

def create_default_config(user_id):
    """Create a default configuration for a new user"""
    default_config = {
        "base_url": "",
        "container_selector": "",
        "fields": {},
        "scroll": False,
        "scroll_wait": 3,
        "initial_wait": 3,
        "paginate": False,
        "start_page": 1,
        "max_pages": 1,
        "next_page_selector": "",
        "page_wait": 2,
        "max_scroll_attempts": 20,
        "load_more_selector": "",
        "load_more_wait": 3,
        "scrape_subpages": False,
        "subpage_wait": 3,
        "subpage_fields": {},
        "output_json": "",
        "output_excel": "",
        "concurrent_settings": {
            "max_concurrent_jobs": 3,
            "base_request_delay": 2,
            "max_concurrent_requests": 2,
            "job_spacing_delay": 3
        }
    }
    
    # Ensure user configs directory exists
    os.makedirs(os.path.join('data', 'user_configs'), exist_ok=True)
    
    # Save the default config
    config_path = get_user_config_path(user_id)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(default_config, f, indent=4)
    
    return default_config

@app.route('/ping', methods=['GET'])
def ping():
    """Simple endpoint to test if the server is running"""
    logger.info("Ping request received")
    
    # Get user ID from header or query parameter
    user_id = request.headers.get('X-User-Id', 'anonymous')
    
    # If header doesn't contain user_id, try query parameter as fallback
    if user_id == 'anonymous' and 'userId' in request.args:
        user_id = request.args.get('userId')
        logger.info(f"Using userId from query parameter: {user_id}")
    
    return jsonify({
        "status": "success",
        "message": "Pong! Server is running.",
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id
    })

@app.route('/', methods=['GET'])
def welcome():
    return jsonify({"message": "Welcome to the Web Scraper API! hari"})

@app.route('/ws')
def handle_websocket():
    if request.environ.get('wsgi.websocket'):
        ws = request.environ['wsgi.websocket']
        while True:
            message = ws.receive()
            ws.send(message)
    return ''

@app.route('/run-scraper', methods=['POST'])
def run_scraper():
    try:
        # Get user ID from request
        user_id = request.json.get('user_id')
        if not user_id:
            return jsonify({
                "status": "error",
                "message": "No user ID provided"
            }), 400
        
        print(f"User ID from request: {user_id}")
        
        # Get user config path
        user_config_path = get_user_config_path(user_id)
        
        # Check if config exists
        if not os.path.exists(user_config_path):
            # Create default config if it doesn't exist
            create_default_config(user_id)
        
        # Load user's configuration
        with open(user_config_path, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
        
        # Check concurrent job limits
        max_jobs = user_config.get("concurrent_settings", {}).get("max_concurrent_jobs", 3)
        user_jobs = [job for job in active_jobs.values() if job.user_id == user_id]
        
        if len(user_jobs) >= max_jobs:
            return jsonify({
                "status": "error",
                "message": f"Maximum number of concurrent jobs ({max_jobs}) reached for user {user_id}. Please wait for some jobs to complete."
            }), 429
        
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Create new job
        job = ScraperJob(job_id, user_id)
        active_jobs[job_id] = job
        
        # Start scraper in separate thread
        threading.Thread(target=run_scraper_process, args=(job,)).start()
        
        print(f"Active jobs: {list(active_jobs.keys())}")
        
        return jsonify({
            "status": "success",
            "message": "Scraper started successfully",
            "job_id": job_id,
            "user_id": user_id
        })
    except Exception as e:
        print(f"Error in run_scraper: {str(e)}")  # Add debug logging
        return jsonify({"status": "error", "message": str(e)}), 500

def run_scraper_process(job):
    try:
        # Create unique config for this job
        job_config = create_job_config(job)
        
        # Log the start of scraping
        logger.info(f"Starting scraper job {job.job_id} for user {job.user_id}")
        
        # Send initial state message using Socket.IO
        send_state_update(job.job_id, "running")
        send_log_to_clients(job.job_id, "Starting scraper process...")
        
        # Update job status
        job.status = "running"
        
        # Start the scraper process with unbuffered output and explicit encoding
        process = subprocess.Popen(
            ['python', '-u', 'scrap.py', '--config', job_config],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding='utf-8',
            errors='replace',  # Replace invalid characters instead of failing
            bufsize=1
        )
        
        job.process = process
        
        # Monitor the process output
        while True:
            try:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    # Strip whitespace and send log message using Socket.IO
                    stripped_output = output.strip()
                    if stripped_output:
                        send_log_to_clients(job.job_id, stripped_output)
                        
                        # Check if this is a completion message
                        if "Scraper completed successfully" in stripped_output:
                            job.should_stop = True
                            logger.info(f"Setting should_stop flag for job {job.job_id}")
            except UnicodeDecodeError as e:
                # Handle any remaining encoding issues
                logger.error(f"Unicode decode error: {str(e)}")
                # Continue processing
                continue
        
        # Get the return code
        return_code = process.poll()
        
        # Send final state based on return code
        if return_code == 0:
            # First update the job status
            job.status = "completed"
            job.completion_time = datetime.now()  # Set completion time
            # Then send the state update
            send_state_update(job.job_id, "completed")
            send_log_to_clients(job.job_id, "Scraper completed successfully")
            
            # Always stop the scraper after successful completion
            logger.info(f"Stopping scraper {job.job_id} after successful completion")
            send_log_to_clients(job.job_id, "Stopping scraper after successful completion")
            
            # Clean up the process
            if job.process:
                try:
                    job.process.terminate()
                    job.process.wait(timeout=5)
                except:
                    if job.process:
                        job.process.kill()
                job.process = None

            # Send one final state update to ensure UI is updated
            send_state_update(job.job_id, "completed")
        else:
            send_state_update(job.job_id, "failed")
            send_log_to_clients(job.job_id, f"Scraper failed with return code {return_code}")
            job.status = "failed"
    except Exception as e:
        logger.error(f"Error in scraper process: {str(e)}")
        send_state_update(job.job_id, "error")
        send_log_to_clients(job.job_id, f"Error in scraper process: {str(e)}")
        job.status = "error"
    finally:
        # Clean up the process if it's still running
        if job.process and job.process.poll() is None:
            try:
                job.process.terminate()
                job.process.wait(timeout=5)
            except:
                if job.process:
                    job.process.kill()
            job.process = None

@app.route('/get-config', methods=['GET'])
def get_config():
    try:
        # Get user ID from request
        user_id = request.headers.get('X-User-Id', 'anonymous')
        print(f"User ID: {user_id}")
        user_config_path = get_user_config_path(user_id)

        # If user config exists, return it
        if os.path.exists(user_config_path):
            with open(user_config_path, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        
        # Otherwise return base config
        return jsonify(get_base_config())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/update-config', methods=['POST', 'OPTIONS'])
def update_config():
    try:
        logger.info(f"Received {request.method} request to /update-config")
        logger.info(f"Headers: {dict(request.headers)}")
        
        if request.method == 'OPTIONS':
            # Handling preflight request
            response = jsonify({'status': 'ok'})
            response.headers.add('Access-Control-Allow-Origin', FRONTEND_URL)
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type, X-User-Id')
            response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
            response.headers.add('Access-Control-Allow-Credentials', 'true')
            return response

        # Handle POST request
        config_data = request.get_json()
        if not config_data:
            logger.error("No configuration data provided")
            return jsonify({
                "status": "error",
                "message": "No configuration data provided"
            }), 400

        # Get user ID from request
        user_id = request.headers.get('X-User-Id')
        if not user_id:
            logger.error("No user ID provided in headers")
            return jsonify({
                "status": "error",
                "message": "No user ID provided"
            }), 400
            
        logger.info(f"Updating configuration for user {user_id}")
        logger.info(f"Configuration data: {json.dumps(config_data, indent=2)}")
        
        # Ensure user configs directory exists
        os.makedirs(os.path.join('data', 'user_configs'), exist_ok=True)
        
        # Add concurrent scraping settings if not present
        if "concurrent_settings" not in config_data:
            config_data["concurrent_settings"] = {
                "max_concurrent_jobs": 3,
                "base_request_delay": 2,
                "max_concurrent_requests": 2,
                "job_spacing_delay": 3
            }
        
        # Save user-specific config
        user_config_path = get_user_config_path(user_id)
        with open(user_config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        
        logger.info(f"Successfully updated configuration for user {user_id}")
        
        return jsonify({
            "status": "success",
            "message": "Configuration updated successfully",
            "user_id": user_id
        })
            
    except Exception as e:
        logger.error(f"Error updating configuration: {str(e)}")
        logger.exception(e)  # This will log the full stack trace
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

def create_job_config(job):
    """Create a job-specific config file"""
    try:
        # Get user-specific config or fall back to base config
        user_config_path = get_user_config_path(job.user_id)
        if os.path.exists(user_config_path):
            with open(user_config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"Using configuration for user {job.user_id}")
        else:
            config = get_base_config()
            logger.info(f"No user configuration found for {job.user_id}, using base config")
        
        # Add job-specific settings
        job_config = {
            **config,
            "job_id": job.job_id,
            "user_id": job.user_id,
            "concurrent": True,
            "output_dir": job.output_dir,
            "output_json": os.path.join(job.output_dir, 'scraped_data.json'),
            "output_excel": os.path.join(job.output_dir, 'scraped_data.xlsx'),
            "log_file": os.path.join(job.output_dir, 'scraper.log'),
            "request_delay": config.get("concurrent_settings", {}).get("base_request_delay", 1) * (len(active_jobs) + 1),
            "max_concurrent_requests": config.get("concurrent_settings", {}).get("max_concurrent_requests", 2),
            "job_start_time": job.start_time.isoformat(),
            "headless": True  # Force headless mode for concurrent jobs
        }
        
        # Save job-specific config
        job_config_path = os.path.join(job.output_dir, 'config.json')
        with open(job_config_path, 'w', encoding='utf-8') as f:
            json.dump(job_config, f, indent=4)
            
        logger.info(f"Created job configuration at {job_config_path}")
        return job_config_path
    except Exception as e:
        logger.error(f"Failed to create job config: {str(e)}")
        raise

@app.route('/stop-scraper', methods=['POST'])
def stop_scraper():
    try:
        # Get job_id from request
        job_id = request.json.get('job_id')
        if not job_id:
            return jsonify({
                "status": "error", 
                "message": "No job ID provided"
            }), 400
            
        if job_id not in active_jobs:
            return jsonify({
                "status": "error", 
                "message": f"Invalid job ID: {job_id}"
            }), 404
        
        job = active_jobs[job_id]
        
        # Set the should_stop flag to signal the scraper to stop gracefully
        job.should_stop = True
        
        # Send stopping state update
        send_state_update(job_id, "stopping")
        send_log_to_clients(job_id, "Stopping scraper...")
        
        # Wait for a short time to allow graceful shutdown
        time.sleep(2)
        
        # If process is still running, force terminate it
        if job.process and job.process.poll() is None:
            try:
                job.process.terminate()
                job.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                job.process.kill()
                send_log_to_clients(job_id, "Force killed scraper process")
            
            job.process = None
        
        # Update job status
        job.status = "stopped"
        job.completion_time = datetime.now()
        
        # Send final state update
        send_state_update(job_id, "stopped")
        send_log_to_clients(job_id, "Scraper stopped by user")
        
        return jsonify({
            "status": "success",
            "message": "Scraper stopped successfully"
        })
        
    except Exception as e:
        logger.error(f"Error stopping scraper: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Failed to stop scraper: {str(e)}"
        }), 500

@app.route('/job-status', methods=['GET'])
def get_job_status():
    job_id = request.args.get('job_id')
    if not job_id or job_id not in active_jobs:
        return jsonify({"status": "error", "message": "Invalid job ID"}), 404
    
    job = active_jobs[job_id]
    return jsonify({
        "status": job.status,
        "start_time": job.start_time.isoformat(),
        "user_id": job.user_id
    })

@app.route('/job-logs', methods=['GET'])
def get_job_logs():
    job_id = request.args.get('job_id')
    if not job_id or job_id not in active_jobs:
        return jsonify({"status": "error", "message": "Invalid job ID"}), 404
    
    job = active_jobs[job_id]
    logs = []
    while not job.log_queue.empty():
        logs.append(job.log_queue.get())
    
    return jsonify({"logs": logs})

@app.route('/download-results', methods=['GET'])
def download_results():
    job_id = request.args.get('job_id')
    file_type = request.args.get('type', 'json')  # 'json' or 'excel'
    
    if not job_id or job_id not in active_jobs:
        return jsonify({"status": "error", "message": "Invalid job ID"}), 404
    
    job = active_jobs[job_id]
    
    if file_type == 'json':
        file_path = os.path.join(job.output_dir, 'scraped_data.json')
    else:
        file_path = os.path.join(job.output_dir, 'scraped_data.xlsx')
    
    if not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "Results file not found"}), 404
    
    return send_file(file_path, as_attachment=True)

@app.route('/get-scraped-data/<job_id>', methods=['GET'])
def get_scraped_data_by_id(job_id):
    try:
        # Construct the path to the job's output directory
        output_dir = os.path.join('output', job_id)
        json_file = os.path.join(output_dir, 'scraped_data.json')
        
        # Check if the directory and file exist
        if not os.path.exists(output_dir) or not os.path.exists(json_file):
            return jsonify({
                "status": "error",
                "message": f"No data found for job ID: {job_id}"
            }), 404
            
        # Read and return the JSON data
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return jsonify(data)
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error retrieving data: {str(e)}"
        }), 500

@app.route('/get-excel-data/<job_id>', methods=['GET'])
def get_excel_data_by_id(job_id):
    try:
        # Construct the path to the job's output directory
        output_dir = os.path.join('output', job_id)
        excel_file = os.path.join(output_dir, 'scraped_data.xlsx')
        
        # Check if the directory and file exist
        if not os.path.exists(output_dir) or not os.path.exists(excel_file):
            return jsonify({
                "status": "error",
                "message": f"No Excel data found for job ID: {job_id}"
            }), 404
            
        return send_file(excel_file, as_attachment=True)
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error retrieving Excel data: {str(e)}"
        }), 500

@app.route('/list-jobs', methods=['GET'])
def list_jobs():
    try:
        jobs = []
        output_dir = 'output'
        
        # Check if output directory exists
        if not os.path.exists(output_dir):
            return jsonify([])
            
        # List all job directories
        for job_id in os.listdir(output_dir):
            job_dir = os.path.join(output_dir, job_id)
            if os.path.isdir(job_dir):
                # Try to get job status from log file
                log_file = os.path.join(job_dir, 'scraper.log')
                status = "completed"  # Default status
                start_time = None
                user_id = None
                
                if os.path.exists(log_file):
                    with open(log_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            if "Job started for user" in line:
                                # Extract timestamp and user ID
                                try:
                                    # Split by first occurrence of " - INFO - "
                                    timestamp_part, rest = line.split(" - INFO - ", 1)
                                    # Parse the timestamp
                                    dt = datetime.strptime(timestamp_part.strip(), '%Y-%m-%d %H:%M:%S,%f')
                                    start_time = dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'  # Convert to ISO format with milliseconds
                                    # Extract user ID
                                    user_id = rest.split("Job started for user ")[1].split(" ")[0]
                                except (ValueError, IndexError) as e:
                                    logger.error(f"Error parsing timestamp from log: {e}")
                                    start_time = None
                                break
                
                # Check if job is in active_jobs
                if job_id in active_jobs:
                    status = active_jobs[job_id].status
                    start_time = active_jobs[job_id].start_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                    user_id = active_jobs[job_id].user_id
                
                jobs.append({
                    "id": job_id,
                    "status": status,
                    "start_time": start_time,
                    "user_id": user_id or "unknown"
                })
        
        return jsonify(jobs)
            
    except Exception as e:
        logger.error(f"Error in list_jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Error listing jobs: {str(e)}"
        }), 500

# Filter function to remove Chrome driver exception messages
def should_filter_log_message(message):
    """Check if a log message should be filtered out."""
    if isinstance(message, str):
        try:
            # Try to parse as JSON
            parsed = json.loads(message)
            log_content = parsed.get("message", "")
            
            # Check for Chrome driver exception patterns
            if "Exception ignored in: <function Chrome.__del__" in log_content or \
               "OSError: [WinError 6] The handle is invalid" in log_content:
                return True
        except json.JSONDecodeError:
            # Not valid JSON, check the raw message
            if "Exception ignored in: <function Chrome.__del__" in message or \
               "OSError: [WinError 6] The handle is invalid" in message:
                return True
        except Exception as e:
            # Log any other errors but don't filter the message
            logger.debug(f"Error in should_filter_log_message: {str(e)}")
    return False

async def start_websocket_server():
    try:
        # Log WebSocket server startup
        logger.info(f"🚀 WEBSOCKET SERVER STARTING on ws://{WS_HOST}:{WS_PORT}")
        
        try:
            # Start WebSocket server with configuration from environment
            server = await websockets.serve(
                websocket_handler, 
                WS_HOST,
                WS_PORT,
                ping_interval=WS_PING_INTERVAL,
                ping_timeout=WS_PING_TIMEOUT,
                close_timeout=WS_CLOSE_TIMEOUT
            )
            
            logger.info(f"✅ WEBSOCKET SERVER RUNNING on ws://{WS_HOST}:{WS_PORT}")
            
            # Keep server running forever
            await asyncio.Future()
        except OSError as e:
            if "address already in use" in str(e).lower():
                alt_port = find_available_port(WS_PORT + 1)
                logger.warning(f"WebSocket port {WS_PORT} is in use. Trying alternative port {alt_port}")
                
                # Try with alternative port
                server = await websockets.serve(
                    websocket_handler, 
                    WS_HOST,
                    alt_port,
                    ping_interval=WS_PING_INTERVAL,
                    ping_timeout=WS_PING_TIMEOUT,
                    close_timeout=WS_CLOSE_TIMEOUT
                )
                
                logger.info(f"✅ WEBSOCKET SERVER RUNNING on ws://{WS_HOST}:{alt_port}")
                
                # Keep server running forever
                await asyncio.Future()
            else:
                raise
                
    except Exception as e:
        logger.error(f"WebSocket server error: {str(e)}", exc_info=True)
        # Try to restart
        await asyncio.sleep(5)
        await start_websocket_server()

def start_websocket_server_thread():
    try:
        # Start the WebSocket server with better error handling
        try:
            loop.run_until_complete(start_websocket_server())
        except Exception as e:
            print(f"Error in WebSocket server main loop: {e}")
            logger.error(f"Error in WebSocket server main loop: {str(e)}", exc_info=True)
    except Exception as e:
        print(f"Error starting WebSocket server thread: {e}")
        logger.error(f"WebSocket server thread error: {str(e)}", exc_info=True)
    finally:
        try:
            # Clean up the event loop
            if loop.is_running():
                loop.stop()
            if not loop.is_closed():
                loop.close()
            print("WebSocket server thread closed")
        except Exception as e:
            print(f"Error cleaning up WebSocket server: {e}")
            logger.error(f"Error cleaning up WebSocket server: {str(e)}")

def check_and_stop_completed_scrapers():
    """Periodically check for and stop completed scrapers."""
    try:
        current_time = datetime.now()
        for job_id, job in list(active_jobs.items()):
            # Check if the job is completed but still has a process
            if job.status == "completed" and job.process:
                logger.info(f"Stopping completed scraper {job_id} immediately")
                try:
                    job.process.terminate()
                    job.process.wait(timeout=1)  # Reduced timeout to 1 second
                except:
                    if job.process:
                        job.process.kill()
                job.process = None
                
                # Set completion time if not already set
                if not job.completion_time:
                    job.completion_time = current_time
            
            # Remove completed jobs from active_jobs but keep their files
            if job.status == "completed" and job.completion_time:
                try:
                    # Remove the job from active_jobs but keep the output directory
                    del active_jobs[job_id]
                    logger.info(f"Removed completed job {job_id} from active jobs")
                except Exception as e:
                    logger.error(f"Error removing job {job_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Error in check_and_stop_completed_scrapers: {str(e)}")

# Start a background thread to periodically check for completed scrapers
def start_cleanup_thread():
    def cleanup_loop():
        while True:
            try:
                check_and_stop_completed_scrapers()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in cleanup loop: {str(e)}")
                time.sleep(60)  # Wait before retrying
    
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    logger.info("Started cleanup thread for completed scrapers")

# Start the cleanup thread when the server starts
start_cleanup_thread()

# Add a new route for force shutdown
@app.route('/force-shutdown', methods=['POST'])
def force_shutdown():
    """Force shutdown the server immediately"""
    try:
        # Force stop all active jobs
        for job in active_jobs.values():
            if job.process:
                try:
                    job.process.kill()
                except:
                    pass
                job.process = None
                job.status = "stopped"
        
        # Force cleanup
        for job_id, job in list(active_jobs.items()):
            try:
                if os.path.exists(job.output_dir):
                    import shutil
                    shutil.rmtree(job.output_dir, ignore_errors=True)
            except:
                pass
            del active_jobs[job_id]
        
        # Force exit
        os._exit(0)
    except Exception as e:
        print(f"Error during force shutdown: {e}")
        os._exit(1)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

def main():
    init_data_directories()
    logger.info("Initialized data directories")
    
    # Log the port before starting the Flask server with SocketIO
    logger.info(f"Starting Flask server on port {PORT}")
    
    try:
        # Start the Flask server with SocketIO
        socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=DEBUG)
    except OSError as e:
        if "Only one usage of each socket address" in str(e):
            alt_port = find_available_port(PORT + 1)
            logger.warning(f"Port {PORT} is in use. Trying alternative port {alt_port}")
            try:
                socketio.run(app, host='0.0.0.0', port=alt_port, debug=DEBUG)
            except Exception as e2:
                logger.error(f"Failed to start server on alternative port: {str(e2)}")
                sys.exit(1)
        else:
            logger.error(f"Failed to start server: {str(e)}")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error starting server: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()