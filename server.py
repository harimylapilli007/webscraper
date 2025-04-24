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
from flask_socketio import SocketIO, emit

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
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')

# Get WebSocket configuration from environment
WS_PING_INTERVAL = int(os.environ.get('WS_PING_INTERVAL', 25))
WS_PING_TIMEOUT = int(os.environ.get('WS_PING_TIMEOUT', 20))
WS_CLOSE_TIMEOUT = int(os.environ.get('WS_CLOSE_TIMEOUT', 20))
WS_HOST = os.environ.get('WS_HOST', '0.0.0.0')
WS_PORT = int(os.environ.get('WS_PORT', PORT))

# Get allowed origins from environment
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*').split(',')

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

# Initialize SocketIO with CORS settings
logger.info("Initializing Socket.IO with configuration:")
logger.info(f"Ping Interval: {WS_PING_INTERVAL}")
logger.info(f"Ping Timeout: {WS_PING_TIMEOUT}")
logger.info(f"Close Timeout: {WS_CLOSE_TIMEOUT}")

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_interval=10000,  # Reduced from 25000
    ping_timeout=5000,    # Reduced from 20000
    logger=True,
    engineio_logger=True,
    transports=['websocket'],  # Only use websocket, no polling
    async_mode='gevent',
    max_http_buffer_size=1e8,
    async_handlers=True,
    monitor_clients=True,
    allow_upgrades=True,
    cookie=False,
    path='socket.io/',
    ping_interval_grace_period=3000,  # Reduced from 5000
    max_retries=5,  # Add max retries
    reconnection=True,
    reconnection_attempts=5,
    reconnection_delay=1000,
    reconnection_delay_max=5000
)

logger.info("Socket.IO initialized successfully")

# Configure CORS with more specific settings
CORS(app, resources={
    r"/*": {
        "origins": ALLOWED_ORIGINS,
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-User-Id"],
        "supports_credentials": True,
        "max_age": 3600
    }
})

# Store WebSocket clients
clients = {}

# Add request logging middleware
@app.before_request
def log_request_info():
    logger.info(f"Request Method: {request.method}")
    logger.info(f"Request Path: {request.path}")
    logger.info("Request Headers:")
    for header, value in request.headers:
        logger.info(f"  {header}: {value}")
    
    # Log user ID specifically
    user_id = request.headers.get('X-User-Id', 'anonymous')
    logger.info(f"User ID from header: {user_id}")

# Add response logging middleware
@app.after_request
def after_request(response):
    logger.info(f"Response Status: {response.status}")
    logger.info("Response Headers:")
    for header, value in response.headers:
        logger.info(f"  {header}: {value}")
    return response

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
connected_clients = {}  # Changed to dict to store user_id for each client

def signal_handler(sig, frame):
    print("Shutting down gracefully...")
    for job in active_jobs.values():
        if job.process:
            try:
                job.process.terminate()
                job.process.wait(timeout=5)
            except:
                job.process.kill()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# SocketIO event handlers
@socketio.on('connect')
def handle_connect():
    client_id = request.sid
    logger.info(f"Client connected: {client_id}")
    logger.info(f"Request headers: {dict(request.headers)}")
    logger.info(f"Request environment: {dict(request.environ)}")
    # Store the client ID without a user ID initially
    connected_clients[client_id] = None

@socketio.on('disconnect')
def handle_disconnect():
    client_id = request.sid
    logger.info(f"Client disconnected: {client_id}")
    if client_id in connected_clients:
        del connected_clients[client_id]

@socketio.on('init')
def handle_init(data):
    client_id = request.sid
    user_id = data.get('user_id')
    logger.info(f"Init received from client {client_id} with user_id {user_id}")
    if user_id:
        connected_clients[client_id] = user_id
        if user_id not in clients:
            clients[user_id] = set()
        clients[user_id].add(client_id)
        logger.info(f"✅ WEBSOCKET CLIENT REGISTERED - User ID: {user_id} - SID: {client_id}")
        # Send a confirmation message back to the client
        socketio.emit('connection', {
            'type': 'connection',
            'message': 'Connected successfully',
            'user_id': user_id,
            'timestamp': datetime.now().isoformat()
        }, room=client_id)

def send_log_to_clients(job_id: str, message: str):
    """Send a log message to all clients associated with the job."""
    try:
        # Get the job object
        job = active_jobs.get(job_id)
        if not job:
            logger.warning(f"No job found with ID {job_id}")
            return
            
        # Get the user ID from the job object
        user_id = job.user_id
        if not user_id:
            logger.warning(f"No user ID found for job {job_id}")
            return

        # Construct the message data in the exact format the frontend expects
        data = {
            'type': 'log',  # Explicitly set type to 'log'
            'job_id': job_id,
            'user_id': user_id,
            'message': message,
            'timestamp': datetime.now().isoformat()  # Add ISO format timestamp
        }

        # Log what we're about to send (truncated for readability)
        logger.debug(f"Sending log to clients: {message[:100]}...")

        # Get all clients for this user
        user_clients = clients.get(user_id, set())
        if not user_clients:
            logger.warning(f"No clients found for user {user_id}")
            return

        # Send to all clients for this user
        for client in user_clients:
            try:
                socketio.emit('log', data, room=client)
                logger.debug(f"Log sent to client {client}")
            except Exception as e:
                logger.error(f"Error sending log to client {client}: {e}")

    except Exception as e:
        logger.error(f"Error in send_log_to_clients: {e}")

def send_state_update(job_id, status):
    """Send a state update to all connected clients."""
    try:
        # Get the user ID from the job
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
        
        # Send to all clients for this user
        if user_id in clients:
            for client_id in clients[user_id]:
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

@app.route('/', methods=['GET'])
def welcome():
    return jsonify({"message": "Welcome to the Web Scraper API!"})

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
        print(f"Creating new job {job_id} for user {user_id}")
        
        # Create new job
        job = ScraperJob(job_id, user_id)
        active_jobs[job_id] = job
        
        # Add small delay between job starts to prevent resource contention
        job_spacing_delay = user_config.get("concurrent_settings", {}).get("job_spacing_delay", 2)
        time.sleep(job_spacing_delay)
        
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
                        logger.info(f"Scraper output: {stripped_output}")
                        send_log_to_clients(job.job_id, stripped_output)
                        
                        # Check if this is a completion message
                        if "Scraper completed successfully" in stripped_output:
                            # Set the flag to indicate we should stop the scraper
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
        send_state_update(job.job_id, "failed")
        send_log_to_clients(job.job_id, f"Error: {str(e)}")
        job.status = "failed"
    finally:
        # Clean up
        if hasattr(job, 'process') and job.process:
            try:
                job.process.terminate()
                job.process.wait(timeout=5)
            except:
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
    print("Request data:", {
        "json": request.get_json(silent=True),
        "form": request.form.to_dict(),
        "args": request.args.to_dict(),
        "data": request.data.decode('utf-8', errors='ignore') if request.data else None
    })

    # Try to get job_id from different request formats
    job_id = None
    try:
        if request.is_json:
            data = request.get_json()
            job_id = data.get('job_id') if data else None
        if not job_id:
            job_id = request.form.get('job_id')
        if not job_id:
            job_id = request.args.get('job_id')
        if not job_id and request.data:
            # Try parsing raw data as JSON
            try:
                data = json.loads(request.data.decode('utf-8'))
                job_id = data.get('job_id')
            except:
                pass

    except Exception as e:
        print(f"Error parsing request: {str(e)}")

    print(f"Extracted job_id: {job_id}")
    print(f"Active jobs: {list(active_jobs.keys())}")

    if not job_id:
        return jsonify({
            "status": "error", 
            "message": "No job ID provided",
            "help": "Please provide job_id in the request body or as a query parameter"
        }), 400
        
    if job_id not in active_jobs:
        return jsonify({
            "status": "error", 
            "message": f"Invalid job ID: {job_id}",
            "available_jobs": list(active_jobs.keys())
        }), 404
    
    job = active_jobs[job_id]
    try:
        if job.process:
            # Notify about stopping
            state_message = json.dumps({
                "type": "state",
                "status": "stopping",
                "job_id": job_id
            })
            job.log_queue.put(state_message)
            job.log_queue.put("Stopping scraper...")
            
            # Close stdout and terminate
            if job.process.stdout:
                job.process.stdout.close()
            
            job.process.terminate()
            try:
                job.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                job.process.kill()
                job.log_queue.put("Force killed scraper process")
            
            job.process = None
            job.status = "stopped"
            
            # Final state update
            state_message = json.dumps({
                "type": "state",
                "status": "stopped",
                "job_id": job_id
            })
            job.log_queue.put(state_message)
        
        return jsonify({
            "status": "success",
            "message": "Scraper stopped successfully"
        })
        
    except Exception as e:
        error_msg = f"Error stopping scraper: {str(e)}"
        job.status = "error"
        state_message = json.dumps({
            "type": "state",
            "status": "error",
            "message": error_msg,
            "job_id": job_id
        })
        job.log_queue.put(state_message)
        job.log_queue.put(error_msg)
        
        return jsonify({"status": "error", "message": error_msg}), 500

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
    """Periodically check for and stop completed scrapers and delete old files."""
    try:
        current_time = datetime.now()
        for job_id, job in list(active_jobs.items()):
            # Check if the job is completed but still has a process
            if job.status == "completed" and job.process:
                logger.info(f"Stopping completed scraper {job_id} that was missed by automatic stopping")
                try:
                    job.process.terminate()
                    job.process.wait(timeout=5)
                except:
                    if job.process:
                        job.process.kill()
                job.process = None
                
                # Set completion time if not already set
                if not job.completion_time:
                    job.completion_time = current_time
            
            # Check for files older than 5 minutes
            if job.status == "completed" and job.completion_time:
                time_diff = (current_time - job.completion_time).total_seconds()
                if time_diff >= 300:  # 5 minutes in seconds
                    try:
                        # Delete the output directory and its contents
                        if os.path.exists(job.output_dir):
                            import shutil
                            shutil.rmtree(job.output_dir)
                            logger.info(f"Deleted output files for job {job_id} after 5 minutes")
                            
                            # Remove the job from active_jobs
                            del active_jobs[job_id]
                    except Exception as e:
                        logger.error(f"Error deleting files for job {job_id}: {str(e)}")
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

def main():
    init_data_directories()
    logger.info("Initialized data directories")
    
    # Log the port before starting the Flask server with SocketIO
    logger.info(f"Starting Flask server on port {PORT}")
    
    # Start the Flask server with SocketIO
    socketio.run(app, host='0.0.0.0', port=PORT, debug=DEBUG)

if __name__ == '__main__':
    main()