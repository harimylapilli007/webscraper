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

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Get configuration from environment
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
PORT = int(os.environ.get('PORT', 8000))
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')
WEBSOCKET_HOST = os.environ.get('WEBSOCKET_HOST', 'localhost')
WEBSOCKET_PORT = int(os.environ.get('WEBSOCKET_PORT', 6789))

# Configure CORS with more specific settings
CORS(app, resources={
    r"/*": {
        "origins": [FRONTEND_URL],  # Use frontend URL from environment
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-User-Id", "Authorization"],
        "expose_headers": ["Content-Type", "X-User-Id"],
        "supports_credentials": True
    }
})

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

loop = asyncio.new_event_loop()

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
        self.output_dir = f"output/{job_id}"
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
    for task in asyncio.all_tasks(loop):
        task.cancel()
    loop.call_soon_threadsafe(loop.stop)
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

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
        
        # Check if any clients are connected for this user
        client_count = sum(1 for client_user in connected_clients.values() if client_user == job.user_id)
        logger.info(f"Found {client_count} connected clients for user {job.user_id} before starting job")
        
        if client_count == 0:
            logger.warning(f"No connected clients for user {job.user_id}. Logs may not appear in real-time.")
            logger.warning("Please ensure the frontend is connected before starting the scraper.")
        
        # Send initial state message
        state_message = json.dumps({
            "type": "state",
            "status": "running",
            "job_id": job.job_id,
            "user_id": job.user_id,
            "message": "Starting scraper...",
            "timestamp": datetime.now().isoformat()
        })
        
        # Debug log for monitoring WebSocket messages
        logger.info(f"Preparing to send state message for job {job.job_id}")
        
        # Store message in job log queue first (for history)
        job.log_queue.put(state_message)
        job.status = "running"
        
        # Send to all WebSocket clients for this user
        clients_for_user = [client for client, client_user_id in connected_clients.items() if client_user_id == job.user_id]
        logger.info(f"Sending initial state to {len(clients_for_user)} clients for user {job.user_id}")
        
        for client in clients_for_user:
            try:
                asyncio.run_coroutine_threadsafe(
                    client.send(state_message),
                    loop
                )
            except Exception as e:
                logger.error(f"Error sending state message to client: {e}")
        
        # Add an initial log message to confirm the job is running
        initial_log = json.dumps({
            "type": "log",
            "job_id": job.job_id,
            "user_id": job.user_id,
            "message": "Starting scraper process...",
            "timestamp": datetime.now().isoformat()
        })
        
        # Store in queue for history
        job.log_queue.put(initial_log)
        
        # Send to WebSocket clients
        for client in clients_for_user:
            try:
                asyncio.run_coroutine_threadsafe(
                    client.send(initial_log),
                    loop
                )
            except Exception as e:
                logger.error(f"Error sending initial log to client: {e}")
        
        # Start the scraper process with job-specific config
        process = subprocess.Popen(
            ['python', '-u', 'scrap.py', '--config', job_config],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,  # Line buffered
            text=True,  # Use text mode instead of universal_newlines
            encoding='utf-8',
            errors='replace'
        )
        
        job.process = process
        
        # Read process output line by line
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
                
            if job.status == "stopping":
                logger.info(f"Job {job.job_id} received stop signal")
                break
                
            stripped_line = line.strip()
            if stripped_line:
                logger.info(f"Job {job.job_id}: {stripped_line}")
                
                # Skip Chrome driver exception messages
                if "Exception ignored in: <function Chrome.__del__" in stripped_line or \
                   "OSError: [WinError 6] The handle is invalid" in stripped_line:
                    continue
                
                # Send log message
                log_message = json.dumps({
                    "type": "log",
                    "job_id": job.job_id,
                    "user_id": job.user_id,
                    "message": stripped_line,
                    "timestamp": datetime.now().isoformat()
                })
                
                # Store in queue for history
                job.log_queue.put(log_message)
                
                # Get current connected clients (might have changed since job started)
                clients_for_user = [client for client, client_user_id in connected_clients.items() if client_user_id == job.user_id]
                
                # If no clients connected, log a warning
                if not clients_for_user:
                    if (int(time.time()) % 10) == 0:  # Only log this warning occasionally
                        logger.warning(f"No connected clients for user {job.user_id}. Logs are being queued but not displayed in real-time.")
                
                # Broadcast to relevant websocket clients immediately
                for client in clients_for_user:
                    try:
                        asyncio.run_coroutine_threadsafe(
                            client.send(log_message),
                            loop
                        )
                    except Exception as e:
                        logger.error(f"Error sending message to client: {e}")
                
                # Force flush stdout
                sys.stdout.flush()
        
        # Wait for process to complete
        process.wait()
        
        # Check process return code
        if process.returncode == 0:
            completion_message = json.dumps({
                "type": "state",
                "status": "completed",
                "job_id": job.job_id,
                "user_id": job.user_id,
                "message": "Scraper completed successfully",
                "timestamp": datetime.now().isoformat()
            })
            
            # Store in queue for history
            job.log_queue.put(completion_message)
            job.status = "completed"
            
            # Get current connected clients
            clients_for_user = [client for client, client_user_id in connected_clients.items() if client_user_id == job.user_id]
            
            # Send to WebSocket clients
            for client in clients_for_user:
                try:
                    asyncio.run_coroutine_threadsafe(
                        client.send(completion_message),
                        loop
                    )
                except Exception as e:
                    logger.error(f"Error sending completion message to client: {e}")
        else:
            raise Exception(f"Scraper process exited with code {process.returncode}")
                    
    except Exception as e:
        error_msg = f"Error in scraper process: {str(e)}"
        logger.error(f"Job {job.job_id}: {error_msg}")
        
        # Send error state message
        state_message = json.dumps({
            "type": "state",
            "status": "error",
            "job_id": job.job_id,
            "user_id": job.user_id,
            "message": error_msg,
            "timestamp": datetime.now().isoformat()
        })
        
        # Store in queue for history
        job.log_queue.put(state_message)
        job.status = "error"
        
        # Get current connected clients
        clients_for_user = [client for client, client_user_id in connected_clients.items() if client_user_id == job.user_id]
        
        # Send to WebSocket clients
        for client in clients_for_user:
            try:
                asyncio.run_coroutine_threadsafe(
                    client.send(state_message),
                    loop
                )
            except Exception as e:
                logger.error(f"Error sending error message to client: {e}")
    finally:
        if job.process:
            try:
                if job.process.stdout:
                    job.process.stdout.close()
                job.process.terminate()
                try:
                    job.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    job.process.kill()
            except:
                if job.process:
                    job.process.kill()
            job.process = None
            
        # Send final cleanup message
        cleanup_message = json.dumps({
            "type": "log",
            "job_id": job.job_id,
            "user_id": job.user_id,
            "message": f"Scraper job {job.job_id} ended",
            "timestamp": datetime.now().isoformat()
        })
        
        # Store in queue for history
        job.log_queue.put(cleanup_message)
        
        # Get current connected clients
        clients_for_user = [client for client, client_user_id in connected_clients.items() if client_user_id == job.user_id]
        
        # Send to WebSocket clients
        for client in clients_for_user:
            try:
                asyncio.run_coroutine_threadsafe(
                    client.send(cleanup_message),
                    loop
                )
            except Exception as e:
                logger.error(f"Error sending cleanup message to client: {e}")
        
        logger.info(f"Scraper job {job.job_id} cleanup completed")

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
        except:
            pass
    return False

async def websocket_handler(websocket):
    user_id = None
    client_info = "unknown"
    
    # Track seen messages to avoid duplicates
    seen_messages = set()
    
    try:
        # Get client info for logging
        client_info = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"New WebSocket client connected from {client_info}")
        
        # Wait for initial message with user ID
        message = await websocket.recv()
        logger.info(f"Received initial message: {message}")
        
        try:
            data = json.loads(message)
            if data.get("type") == "init":
                user_id = data.get("user_id")
                if user_id:
                    logger.info(f"✅ WEBSOCKET CLIENT REGISTERED - User ID: {user_id} - IP: {client_info}")
                    # Store the client with the user ID
                    connected_clients[websocket] = user_id
                    
                    # Find any active jobs for this user to use as default job ID
                    default_job_id = None
                    jobs_for_user = [job_id for job_id, job in active_jobs.items() if job.user_id == user_id]
                    if jobs_for_user:
                        default_job_id = jobs_for_user[0]  # Use the first job as default
                        logger.info(f"Set default job ID for user {user_id}: {default_job_id}")
                    
                    # Send connection confirmation
                    confirm_message = json.dumps({
                        "type": "connection",
                        "status": "connected",
                        "user_id": user_id,
                        "client_info": client_info,
                        "job_id": default_job_id or "system",  # Use default or "system" as fallback
                        "message": f"WebSocket connection established for user {user_id} from {client_info}",
                        "timestamp": datetime.now().isoformat()
                    })
                    await websocket.send(confirm_message)
                    
                    # Count and log connected clients for this user
                    client_count = sum(1 for client_user in connected_clients.values() if client_user == user_id)
                    logger.info(f"👥 ACTIVE WEBSOCKET CONNECTIONS: {client_count} for user {user_id}")
                    
                    # Log all active connections
                    active_connections = {}
                    for ws, uid in connected_clients.items():
                        if uid in active_connections:
                            active_connections[uid] += 1
                        else:
                            active_connections[uid] = 1
                    
                    logger.info(f"📊 ALL ACTIVE CONNECTIONS: {json.dumps(active_connections)}")
                    
                    # Send system message with connection information
                    system_message = json.dumps({
                        "type": "log",
                        "job_id": default_job_id or "system",  # Use default or "system" as fallback
                        "user_id": user_id,
                        "message": f"WebSocket client connected from {client_info}",
                        "timestamp": datetime.now().isoformat()
                    })
                    await websocket.send(system_message)
                    
                    # Send initial state of relevant active jobs
                    jobs_for_user = [j for j_id, j in active_jobs.items() if j.user_id == user_id]
                    logger.info(f"Found {len(jobs_for_user)} active jobs for user {user_id}")
                    
                    # Process each job for this user
                    for job_id, job in active_jobs.items():
                        if job.user_id == user_id:
                            # Send current job state
                            initial_state = json.dumps({
                                "type": "state",
                                "status": job.status,
                                "job_id": job_id,
                                "user_id": job.user_id,
                                "client_info": client_info,
                                "message": f"Current job status: {job.status}",
                                "timestamp": datetime.now().isoformat()
                            })
                            await websocket.send(initial_state)
                            
                            # Send test log message to verify logging works
                            test_log = json.dumps({
                                "type": "log",
                                "job_id": job_id,  # This will always have a valid job_id
                                "user_id": job.user_id,
                                "client_info": client_info,
                                "message": f"WebSocket connection test message - Client connected from {client_info}",
                                "timestamp": datetime.now().isoformat()
                            })
                            await websocket.send(test_log)
                            
                            # Send any existing logs
                            log_count = job.log_queue.qsize()
                            if log_count > 0:
                                logger.info(f"Sending {log_count} queued log messages for job {job_id}")
                                
                                # Get all current logs
                                log_messages = []
                                while not job.log_queue.empty():
                                    log_messages.append(job.log_queue.get())
                                
                                # Filter out Chrome driver exception messages
                                filtered_log_messages = [msg for msg in log_messages if not should_filter_log_message(msg)]
                                
                                # Put the messages back in the queue for other clients
                                for msg in filtered_log_messages:
                                    job.log_queue.put(msg)
                                
                                # Send the messages to the client, tracking to prevent duplicates
                                for log_message in filtered_log_messages:
                                    try:
                                        # Filter out Chrome driver exception messages
                                        if should_filter_log_message(log_message):
                                            continue
                                            
                                        if isinstance(log_message, str):
                                            try:
                                                # Try to parse as JSON first
                                                parsed_message = json.loads(log_message)
                                                
                                                # Create message fingerprint for deduplication
                                                msg_content = parsed_message.get("message", "")
                                                job_id = parsed_message.get("job_id", job.job_id)
                                                msg_fingerprint = f"{job_id}:{msg_content}"
                                                
                                                # Skip if we've already sent this message
                                                if msg_fingerprint in seen_messages:
                                                    continue
                                                
                                                # Add to seen messages
                                                seen_messages.add(msg_fingerprint)
                                                
                                                # Ensure job_id is present
                                                if "job_id" not in parsed_message:
                                                    parsed_message["job_id"] = job.job_id
                                                    log_message = json.dumps(parsed_message)
                                                
                                                await websocket.send(log_message)
                                            except json.JSONDecodeError:
                                                # If not JSON, wrap it
                                                # Create message fingerprint
                                                msg_fingerprint = f"{job.job_id}:{log_message}"
                                                
                                                # Skip if seen
                                                if msg_fingerprint in seen_messages:
                                                    continue
                                                
                                                # Add to seen
                                                seen_messages.add(msg_fingerprint)
                                                
                                                message = json.dumps({
                                                    "type": "log",
                                                    "job_id": job.job_id,  # This ensures job_id is always present
                                                    "user_id": job.user_id,
                                                    "message": log_message,
                                                    "timestamp": datetime.now().isoformat()
                                                })
                                                await websocket.send(message)
                                    except Exception as e:
                                        logger.error(f"Error sending log message: {e}")
                else:
                    logger.warning("Client connected without user ID, rejecting connection")
                    await websocket.close(1008, "No user ID provided")
                    return
        except json.JSONDecodeError:
            logger.error("Invalid initial message format")
            await websocket.close(1008, "Invalid message format")
            return

        # Find default job ID to use when no job_id is provided
        default_job_id = None
        jobs_for_user = [job_id for job_id, job in active_jobs.items() if job.user_id == user_id]
        if jobs_for_user:
            default_job_id = jobs_for_user[0]

        # Keep connection alive and handle new messages
        while True:
            try:
                # Small delay to prevent CPU overuse
                await asyncio.sleep(0.1)
                
                # Check for new messages from all relevant jobs
                user_jobs = [job for job in active_jobs.values() if job.user_id == user_id]
                for job in user_jobs:
                    if not job.log_queue.empty():
                        log_count = job.log_queue.qsize()
                        # Only log when there are multiple messages to process
                        if log_count > 1:
                            logger.info(f"Processing {log_count} new log messages for job {job.job_id}")
                        
                        # Limit the size of seen_messages to prevent memory issues
                        if len(seen_messages) > 5000:
                            seen_messages = set(list(seen_messages)[-5000:])
                        
                        while not job.log_queue.empty():
                            try:
                                log_message = job.log_queue.get()
                                
                                # Filter out Chrome driver exception messages
                                if should_filter_log_message(log_message):
                                    continue
                                    
                                if isinstance(log_message, str):
                                    try:
                                        # Try to parse as JSON first
                                        parsed_message = json.loads(log_message)
                                        
                                        # Create message fingerprint for deduplication
                                        msg_content = parsed_message.get("message", "")
                                        job_id = parsed_message.get("job_id", job.job_id)
                                        msg_fingerprint = f"{job_id}:{msg_content}"
                                        
                                        # Skip if we've already sent this message
                                        if msg_fingerprint in seen_messages:
                                            continue
                                        
                                        # Add to seen messages
                                        seen_messages.add(msg_fingerprint)
                                        
                                        # Ensure job_id is present
                                        if "job_id" not in parsed_message:
                                            parsed_message["job_id"] = job.job_id
                                            log_message = json.dumps(parsed_message)
                                        
                                        await websocket.send(log_message)
                                    except json.JSONDecodeError:
                                        # If not JSON, wrap it
                                        # Create message fingerprint
                                        msg_fingerprint = f"{job.job_id}:{log_message}"
                                        
                                        # Skip if seen
                                        if msg_fingerprint in seen_messages:
                                            continue
                                        
                                        # Add to seen
                                        seen_messages.add(msg_fingerprint)
                                        
                                        message = json.dumps({
                                            "type": "log",
                                            "job_id": job.job_id,  # This ensures job_id is always present
                                            "user_id": job.user_id,
                                            "message": log_message,
                                            "timestamp": datetime.now().isoformat()
                                        })
                                        await websocket.send(message)
                            except Exception as e:
                                logger.error(f"Error sending log message: {e}")
                                continue
            except Exception as e:
                logger.error(f"Error in websocket message loop: {e}")
                break
                
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"🔌 WEBSOCKET CLIENT DISCONNECTED - User ID: {user_id} - IP: {client_info if 'client_info' in locals() else 'unknown'}")
    except Exception as e:
        logger.error(f"Websocket handler error: {e}")
    finally:
        if websocket in connected_clients:
            del connected_clients[websocket]
            
            # Count remaining connections for this user
            remaining = sum(1 for client_user in connected_clients.values() if client_user == user_id)
            logger.info(f"👥 REMAINING CONNECTIONS for user {user_id}: {remaining}")
            
            # Log updated active connections
            active_connections = {}
            for ws, uid in connected_clients.items():
                if uid in active_connections:
                    active_connections[uid] += 1
                else:
                    active_connections[uid] = 1
            
            logger.info(f"📊 UPDATED ACTIVE CONNECTIONS: {json.dumps(active_connections)}")

async def start_websocket_server():
    try:
        # Log WebSocket server startup
        websocket_url = f"ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}"
        print(f"Starting WebSocket server on {websocket_url}")
        logger.info(f"🚀 WEBSOCKET SERVER STARTING on {websocket_url}")
        
        # Start WebSocket server with more explicit configuration
        server = await websockets.serve(
            websocket_handler, 
            WEBSOCKET_HOST, 
            WEBSOCKET_PORT,
            ping_interval=30,  # Send ping every 30 seconds
            ping_timeout=10,   # Wait 10 seconds for pong response
            close_timeout=10   # Wait 10 seconds for close handshake
        )
        
        print(f"WebSocket server started successfully on {websocket_url}")
        logger.info(f"✅ WEBSOCKET SERVER RUNNING on {websocket_url}")
        
        # Keep server running forever
        await asyncio.Future()
    except Exception as e:
        print(f"WebSocket server error: {e}")
        logger.error(f"WebSocket server error: {str(e)}", exc_info=True)
        # Try to restart
        await asyncio.sleep(5)
        await start_websocket_server()

def start_websocket_server_thread():
    try:
        # Set the event loop for this thread
        asyncio.set_event_loop(loop)
        
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

def main():
    try:
        # Start WebSocket server in a separate thread
        print("Starting WebSocket server thread...")
        websocket_thread = threading.Thread(target=start_websocket_server_thread, daemon=True)
        websocket_thread.start()
        
        # Wait a moment to ensure WebSocket server is running
        time.sleep(2)
        print("WebSocket server thread started")
        
        # Get host from environment (for Azure compatibility)
        host = os.environ.get('HOST', 'localhost')
        
        print(f"Starting Flask server on http://{host}:{PORT}")
        app.run(host=host, port=PORT, threaded=True, debug=DEBUG)
    except Exception as e:
        print(f"Server startup error: {e}")
        logger.error(f"Server startup error: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main()