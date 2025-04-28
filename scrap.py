from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService
import json
import time
import pandas as pd
import logging
import sys
import os
import argparse
import requests
import zipfile
import io
import platform
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Logger:
    def __init__(self):
        self.logger = logging.getLogger('scraper')
        self.logger.setLevel(logging.INFO)
        
        # Remove any existing handlers to avoid duplicates
        for handler in self.logger.handlers[:]:
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass
            self.logger.removeHandler(handler)
        
        # Create stdout handler with immediate flushing and UTF-8 encoding
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(message)s'))  # Simplified format for frontend display
        handler.flush = sys.stdout.flush  # Ensure immediate flushing
        
        # Set UTF-8 encoding for the handler
        if hasattr(handler.stream, 'reconfigure'):
            handler.stream.reconfigure(encoding='utf-8')
        
        self.logger.addHandler(handler)
        
        # Send initial test messages to verify logging is working
        self.log("===== LOGGER INITIALIZATION =====", level=logging.INFO)
        self.log("Web scraper starting up...", level=logging.INFO)
        self.log("Test message 1: This should appear in the UI", level=logging.INFO)
        self.log("Test message 2: If you can see this, logging is working", level=logging.INFO)
        self.log("Test message 3: Proceeding with scraping...", level=logging.INFO)
        self.log("================================", level=logging.INFO)
        
        # Force immediate flush
        sys.stdout.flush()
        for handler in self.logger.handlers:
            try:
                handler.flush()
            except Exception:
                pass
    
    def add_file_handler(self, log_file):
        """Add a file handler to the logger"""
        if log_file:
            try:
                # Create directory for log file if it doesn't exist
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
                
                # Create and configure file handler with UTF-8 encoding
                file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='a')
                file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
                file_handler.setFormatter(file_formatter)
                
                # Add handler to logger
                self.logger.addHandler(file_handler)
                self.log(f"Added file handler for log file: {log_file}", level=logging.INFO)
            except Exception as e:
                print(f"Error setting up file handler: {str(e)}", file=sys.stderr)
                sys.stderr.flush()
    
    def log(self, message, level=logging.INFO):
        try:
            # Get current timestamp
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            
            # Ensure message is properly encoded
            if isinstance(message, bytes):
                message = message.decode('utf-8', errors='replace')
            elif not isinstance(message, str):
                message = str(message)
            
            # Add emoji support while keeping safe replacements for logging
            message = (message
                .replace('\u2705', '[SUCCESS]')  # ✅
                .replace('\u274c', '[ERROR]')    # ❌
                .replace('\u27a1', '[NEXT]'))    # ➡️
            
            # Add debug prefix to clearly identify messages
            if level == logging.DEBUG:
                formatted_message = f"[{timestamp}] DEBUG: {message}"
            elif level == logging.INFO:
                formatted_message = f"[{timestamp}] INFO - {message}"
            elif level == logging.WARNING:
                formatted_message = f"[{timestamp}] WARNING - {message}"
            elif level == logging.ERROR:
                formatted_message = f"[{timestamp}] ERROR - {message}"
            else:
                formatted_message = f"[{timestamp}] {message}"
            
            # Log the message with proper formatting
            self.logger.log(level, formatted_message)
            
            # Force flush stdout
            sys.stdout.flush()
            
            # Force flush all handlers
            for handler in self.logger.handlers:
                try:
                    handler.flush()
                except Exception:
                    pass
                
        except Exception as e:
            # Print error directly to stderr as last resort
            error_msg = f"Error in logging: {str(e)}"
            print(error_msg, file=sys.stderr)
            sys.stderr.flush()

# Create a global logger instance
logger = Logger()

def download_chromedriver(version=None):
    """Download ChromeDriver manually and return the path to the executable."""
    try:
        # Use default Chrome driver version
        version = version or "114.0.5735.90"
        logger.log(f"Attempting to download ChromeDriver {version} manually...", level=logging.INFO)
        
        # Determine the platform-specific download URL
        system = platform.system()
        if system == "Windows":
            platform_name = "win32"
        elif system == "Linux":
            platform_name = "linux64"
        elif system == "Darwin":  # macOS
            platform_name = "mac64"
        else:
            raise Exception(f"Unsupported platform: {system}")
        
        # Create directory for storing the driver
        driver_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drivers")
        os.makedirs(driver_dir, exist_ok=True)
        
        # Download URL
        download_url = f"https://chromedriver.storage.googleapis.com/{version}/chromedriver_{platform_name}.zip"
        logger.log(f"Downloading from: {download_url}", level=logging.INFO)
        
        # Download the zip file
        response = requests.get(download_url)
        if response.status_code != 200:
            raise Exception(f"Failed to download ChromeDriver. Status code: {response.status_code}")
        
        # Extract the zip file
        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
            zip_file.extractall(driver_dir)
        
        # Set the driver path
        if system == "Windows":
            driver_path = os.path.join(driver_dir, "chromedriver.exe")
        else:
            driver_path = os.path.join(driver_dir, "chromedriver")
            # Make the driver executable on Unix systems
            os.chmod(driver_path, 0o755)
        
        logger.log(f"Successfully downloaded ChromeDriver to: {driver_path}", level=logging.INFO)
        return driver_path
    
    except Exception as e:
        logger.log(f"Failed to download ChromeDriver manually: {str(e)}", level=logging.ERROR)
        return None

def get_chrome_version():
    """Get the installed Chrome version."""
    try:
        if platform.system() == "Windows":
            # Use PowerShell to get Chrome version on Windows
            import subprocess
            cmd = r'(Get-Item "C:\Program Files\Google\Chrome\Application\chrome.exe").VersionInfo.ProductVersion'
            chrome_version = subprocess.check_output(["powershell", "-command", cmd]).decode("utf-8").strip()
            logger.log(f"Detected Chrome version: {chrome_version}", level=logging.INFO)
            return chrome_version
        else:
            # This is a simplified version, more robust version detection might be needed
            logger.log("Chrome version detection not implemented for this OS", level=logging.WARNING)
            return None
    except Exception as e:
        logger.log(f"Error detecting Chrome version: {str(e)}", level=logging.WARNING)
        return None

def get_compatible_chromedriver_version(chrome_version):
    """Return a compatible ChromeDriver version based on Chrome version."""
    # Extract major version number
    match = re.match(r'^(\d+)\.', chrome_version)
    if match:
        chrome_major = match.group(1)
        # Map of compatible ChromeDriver versions for various Chrome versions
        # Based on https://chromedriver.chromium.org/downloads
        version_map = {
            "135": "122.0.6261.94",  # Updated for Chrome 135
            "134": "122.0.6261.94",
            "133": "122.0.6261.94",
            "132": "122.0.6261.94",
            "131": "122.0.6261.94",
            "130": "122.0.6261.94",
            "129": "122.0.6261.94",
            "128": "122.0.6261.94",
            "127": "122.0.6261.94",
            "126": "122.0.6261.94",
            "125": "122.0.6261.94",
            "124": "122.0.6261.94",
            "123": "122.0.6261.94",
            "122": "122.0.6261.94",
            "121": "121.0.6167.85",
            "120": "120.0.6099.109",
            "119": "119.0.6045.105",
            "118": "118.0.5993.70",
            "117": "117.0.5938.149",
            "116": "116.0.5845.96",
            "115": "115.0.5790.102",
            "114": "114.0.5735.90"
        }
        if chrome_major in version_map:
            return version_map[chrome_major]
        else:
            # Default to a version that often works
            return "122.0.6261.94"  # Updated default version
    return "122.0.6261.94"  # Updated default fallback

def setup_driver(headless=True):
    """Initialize and return a Chrome WebDriver instance."""
    # Suppress stderr to hide Chrome driver exit exception messages
    import os
    import sys
    import io
    
    # Redirect stderr to suppress undetected_chromedriver exceptions
    original_stderr = sys.stderr
    sys.stderr = io.StringIO()
    
    try:
        # Get Chrome version for compatible driver
        chrome_version = get_chrome_version()
        if not chrome_version:
            raise Exception("Could not detect Chrome version")
            
        # Extract major version number
        match = re.match(r'^(\d+)\.', chrome_version)
        if not match:
            raise Exception(f"Invalid Chrome version format: {chrome_version}")
            
        chrome_major = match.group(1)
        
        # Use ChromeDriverManager with specific version
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        
        # Configure Chrome options
        chrome_options = Options()
        # if headless:
        #     chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-software-rasterizer')
        
        # Add unique user agent and window size for concurrent jobs
        if 'job_id' in config:
            chrome_options.add_argument(f'--user-agent=WebScraper-Job-{config["job_id"]}')
            chrome_options.add_argument(f'--window-position={hash(config["job_id"]) % 1000},0')
        
        # Set Chrome binary location explicitly
        chrome_options.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        
        # Try to use ChromeDriverManager with version matching
        try:
            # First try with exact version match
            driver_version = f"{chrome_major}.0.0"
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.log(f"Successfully initialized Chrome driver with version {driver_version}", level=logging.INFO)
            return driver
        except Exception as e1:
            logger.log(f"Failed to initialize with exact version match: {str(e1)}", level=logging.WARNING)
            
            try:
                # Try with latest compatible version
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=chrome_options)
                logger.log("Successfully initialized Chrome driver with latest compatible version", level=logging.INFO)
                return driver
            except Exception as e2:
                logger.log(f"Failed to initialize with latest version: {str(e2)}", level=logging.WARNING)
                
                # Try undetected-chromedriver as last resort
                try:
                    import undetected_chromedriver as uc
                    options = uc.ChromeOptions()
                    if headless:
                        options.add_argument('--headless')
                    options.add_argument('--disable-gpu')
                    options.add_argument('--no-sandbox')
                    options.add_argument('--disable-dev-shm-usage')
                    
                    if 'job_id' in config:
                        options.add_argument(f'--user-agent=WebScraper-Job-{config["job_id"]}')
                        options.add_argument(f'--window-position={hash(config["job_id"]) % 1000},0')
                    
                    driver = uc.Chrome(options=options)
                    logger.log("Successfully initialized Chrome with undetected-chromedriver", level=logging.INFO)
                    return driver
                except Exception as e3:
                    logger.log(f"All Chrome driver initialization methods failed", level=logging.ERROR)
                    logger.log(f"Error 1: {str(e1)}", level=logging.ERROR)
                    logger.log(f"Error 2: {str(e2)}", level=logging.ERROR)
                    logger.log(f"Error 3: {str(e3)}", level=logging.ERROR)
                    
                    error_message = """
Chrome driver initialization failed. Please try one of the following solutions:
1. Update Chrome to the latest version
2. Manually download ChromeDriver matching your Chrome version from: https://chromedriver.chromium.org/downloads
3. Add chromedriver.exe to your PATH
4. Try running without headless mode
"""
                    logger.log(error_message, level=logging.ERROR)
                    raise Exception("Unable to initialize Chrome driver. See logs for troubleshooting steps.")
                    
    finally:
        # Restore stderr
        sys.stderr = original_stderr

def validate_config(config):
    required_keys = ["base_url", "container_selector", "fields"]
    for key in required_keys:
        if key not in config:
            logger.log(f"Missing required config key: {key}", level=logging.ERROR)
            return False
            
    # Log concurrent scraping settings
    if config.get("concurrent"):
        logger.log("Concurrent scraping settings:", level=logging.INFO)
        logger.log(f"Job ID: {config.get('job_id')}", level=logging.INFO)
        logger.log(f"User ID: {config.get('user_id')}", level=logging.INFO)
        logger.log(f"Request delay: {config.get('request_delay')}s", level=logging.INFO)
        logger.log(f"Max concurrent requests: {config.get('max_concurrent_requests')}", level=logging.INFO)
    
    return True

def get_total_pages(driver, config):
    """
    Determine the total number of pages available for scraping.
    Returns the total number of pages or None if it can't be determined.
    """
    try:
        # Wait for pagination elements to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, config["next_page_selector"]))
        )
        
        # Try different methods to find total pages
        pagination_elements = driver.find_elements(By.CSS_SELECTOR, config["next_page_selector"]) 
        logger.log(f"Found {len(pagination_elements)} pagination elements", level=logging.INFO)
        
        # Method 1: Look for numeric page links
        page_numbers = []
        for element in pagination_elements:
            try:
                num = int(element.text.strip())
                page_numbers.append(num)
            except ValueError:
                continue
        
        if page_numbers:
            total_pages = max(page_numbers)
            logger.log(f"Found {total_pages} total pages", level=logging.INFO)
            return total_pages
            
        # Method 2: Count page links (excluding next/prev buttons)
        numeric_pages = len([el for el in pagination_elements 
                           if el.text.strip().isdigit()])
        if numeric_pages > 0:
            logger.log(f"Found {numeric_pages} total pages", level=logging.INFO)
            return numeric_pages
            
        # Method 3: If no clear pagination, assume single page
        logger.log("Could not determine total pages, will proceed page by page", level=logging.INFO)
        return None
        
    except Exception as e:
        logger.log(f"Error determining total pages: {str(e)}", level=logging.WARNING)
        return None

def handle_url_based_pagination(driver, current_url, current_page):
    """Handle URL-based pagination when URL contains page parameters.
    
    Args:
        driver: Selenium WebDriver instance
        current_url: Current page URL
        current_page: Current page number
        
    Returns:
        tuple: (bool success, str next_url) indicating if navigation was successful and the next URL
    """
    try:
        # Determine URL structure
        if "page/" in current_url:
            base_url = current_url.split("page/")[0]
            next_url = f"{base_url}page/{current_page + 1}/"
        elif "/page=" in current_url or "?page=" in current_url:
            base_url = current_url.split("page=")[0]
            separator = "&" if "?" in base_url else "?"
            next_url = f"{base_url}{separator}page={current_page + 1}"
        else:
            return False, None
            
        # Try navigating to next page
        old_url = driver.current_url
        driver.get(next_url)
        time.sleep(3)  # Wait for page load
        
        # Verify if page changed successfully
        if driver.current_url != old_url:
            logger.log(f"➡️ Moved to page {current_page + 1} using URL navigation", level=logging.INFO)
            return True, next_url
            
        return False, None
        
    except Exception as e:
        logger.log(f"URL-based navigation failed: {str(e)}", level=logging.WARNING)
        return False, None

def handle_click_based_pagination(driver, next_page_selector, current_page):
    """Handle click-based pagination using next page buttons.
    
    Args:
        driver: Selenium WebDriver instance
        next_page_selector: CSS selector for pagination elements
        current_page: Current page number
        
    Returns:
        bool: True if successfully moved to next page, False otherwise
    """
    try:
        # Find next page button
        next_page = driver.find_element(By.CSS_SELECTOR, next_page_selector)
        
        # Check if next page button is enabled and visible
        if next_page.is_displayed() and next_page.is_enabled():
            # Store current URL to verify page change
            old_url = driver.current_url
            
            # Scroll button into view
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_page)
            time.sleep(2)
            
            # Try clicking
            try:
                driver.execute_script("arguments[0].click();", next_page)
                logger.log(f"➡️ Moving to page {current_page + 1} using JavaScript click", level=logging.INFO)
            except Exception:
                try:
                    next_page.click()
                    logger.log(f"➡️ Moving to page {current_page + 1} using regular click", level=logging.INFO)
                except Exception as click_error:
                    logger.log(f"Failed to click next page button: {str(click_error)}", level=logging.ERROR)
                    return False
            
            # Verify page changed
            time.sleep(3)
            return driver.current_url != old_url
            
        else:
            logger.log("Next page button is not enabled or visible", level=logging.INFO)
            return False
        
    except Exception as e:
        logger.log(f"Click-based navigation failed: {str(e)}", level=logging.WARNING)
        return False

def scrape_subpage(driver, config, url):
    """
    Scrape data from a subpage.
    
    Args:
        driver: Selenium WebDriver instance
        config: Scraping configuration
        url: URL of the subpage to scrape
        
    Returns:
        dict: Extracted data from the subpage
    """
    try:
        # Store current URL to return to main page later
        main_page_url = driver.current_url
        
        # Navigate to subpage
        driver.get(url)
        time.sleep(config.get("subpage_wait", 3))
        
        # Extract data using subpage selectors
        subpage_data = {}
        for key, selector in config.get("subpage_fields", {}).items():
            try:
                if isinstance(selector, dict):
                    elem = driver.find_element(By.CSS_SELECTOR, selector["selector"])
                    subpage_data[key] = elem.get_attribute(selector["attribute"])
                else:
                    elem = driver.find_element(By.CSS_SELECTOR, selector)
                    subpage_data[key] = elem.text.strip()
                logger.log(f"Extracted subpage field '{key}': {subpage_data[key]}", level=logging.INFO)
            except Exception as e:
                subpage_data[key] = None
                logger.log(f"Couldn't extract subpage field '{key}': {e}", level=logging.WARNING)
        
        # Return to main page
        # driver.get(main_page_url)
        # time.sleep(config.get("page_wait", 2))
        
        return subpage_data
        
    except Exception as e:
        logger.log(f"Failed to scrape subpage {url}: {e}", level=logging.ERROR)
        return {}

def handle_load_more_button(driver, config):
    """Handle dynamic 'Load More' or 'Show More' buttons that appear while scrolling.
    
    Args:
        driver: Selenium WebDriver instance
        config: Scraping configuration containing load_more_selector
        
    Returns:
        bool: True if a load more button was found and clicked, False otherwise
    """
    try:
        # Try to find the load more button using the provided selector
        load_more_selector = config.get("load_more_selector")
        if not load_more_selector:
            return False
            
        # Wait briefly for the button to be visible
        try:
            load_more_button = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, load_more_selector))
            )
        except TimeoutException:
            return False
            
        # Check if button is visible and clickable
        if load_more_button.is_displayed() and load_more_button.is_enabled():
            # Get current number of items for verification
            old_count = len(driver.find_elements(By.CSS_SELECTOR, config["container_selector"]))
            
            # Scroll button into view and click
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_button)
            time.sleep(2)
            
            try:
                driver.execute_script("arguments[0].click();", load_more_button)
                logger.log("Clicked 'Load More' button using JavaScript", level=logging.INFO)
            except Exception:
                try:
                    load_more_button.click()
                    logger.log("Clicked 'Load More' button using regular click", level=logging.INFO)
                except Exception as click_error:
                    logger.log(f"Failed to click 'Load More' button: {str(click_error)}", level=logging.WARNING)
                    return False
            
            # Wait for new content to load
            time.sleep(config.get("load_more_wait", 3))
            
            # Verify new items were loaded
            new_count = len(driver.find_elements(By.CSS_SELECTOR, config["container_selector"]))
            if new_count > old_count:
                logger.log(f"Successfully loaded more items ({old_count} -> {new_count})", level=logging.INFO)
                return True
            else:
                logger.log("No new items loaded after clicking 'Load More'", level=logging.WARNING)
                return False
                
        return False
        
    except Exception as e:
        logger.log(f"Error handling 'Load More' button: {str(e)}", level=logging.WARNING)
        return False

def scrape_data(config):
    if not validate_config(config):
        logger.log("Invalid configuration. Exiting.", level=logging.ERROR)
        return

    logger.log("Starting scraper with configuration:", level=logging.INFO)
    logger.log(json.dumps({k: v for k, v in config.items() if k not in ['fields', 'subpage_fields']}, indent=2), level=logging.INFO)

    driver = None
    try:
        driver = setup_driver(config.get("headless", True))
        results = []
        page_num = config.get("start_page", 1)
        max_pages = config.get("max_pages", 10)
        
        # Set up job-specific logging if configured
        if config.get("log_file"):
            logger.log(f"Job started for user {config.get('user_id')} (Job ID: {config.get('job_id')})", level=logging.INFO)
        
        # Phase 1: Collect all main fields and links
        logger.log("Phase 1: Collecting main fields and links from all pages...", level=logging.INFO)
        driver.get(config["base_url"])
        logger.log(f"Navigated to base URL: {config['base_url']}", level=logging.INFO)
        
        # Add delay for concurrent scraping
        if config.get("concurrent"):
            time.sleep(config.get("request_delay", 1))
        else:
            time.sleep(config.get("initial_wait", 5))
        
        # Get total pages if possible
        if config.get("paginate", False):
            total_pages = get_total_pages(driver, config)
            if total_pages:
                logger.log(f"Total pages to scrape: {min(total_pages, max_pages)}", level=logging.INFO)
        
        # Determine pagination type
        current_url = driver.current_url
        is_url_based = "page/" in current_url or "page=" in current_url
        
        while True:
            logger.log(f"Scraping main fields from page {page_num}...", level=logging.INFO)
            
            if page_num > max_pages:
                logger.log(f"Reached maximum page limit ({max_pages}). Stopping.", level=logging.INFO)
                break
            
            # Scroll if needed
            if config.get("scroll", False):
                logger.log("Starting to scroll down the page to load all content...", level=logging.INFO)
                last_height = driver.execute_script("return document.body.scrollHeight")
                scroll_attempts = 0
                max_scroll_attempts = config.get("max_scroll_attempts", 20)  # Prevent infinite scrolling
                
                while scroll_attempts < max_scroll_attempts:
                    # Scroll down
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(config.get("scroll_wait", 2))
                    
                    # Try to find and click load more button
                    if handle_load_more_button(driver, config):
                        scroll_attempts = 0  # Reset counter if we successfully loaded more content
                        logger.log("Found and clicked 'Load More' button, continuing to scroll...", level=logging.INFO)
                        continue
                    
                    # Check if we've reached the bottom
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        scroll_attempts += 1
                        if scroll_attempts >= 3:  # If height hasn't changed after 3 attempts, we're done
                            logger.log("Reached the bottom of the page - no more content to load", level=logging.INFO)
                            break
                    else:
                        scroll_attempts = 0  # Reset counter if height changed
                        logger.log("Scrolling further down to load more content...", level=logging.INFO)
                        
                    last_height = new_height
                
                if scroll_attempts >= max_scroll_attempts:
                    logger.log(f"Reached maximum scroll attempts ({max_scroll_attempts}) - stopping scroll", level=logging.WARNING)

            # Get elements
            containers = driver.find_elements(By.CSS_SELECTOR, config["container_selector"])
            logger.log(f"Found {len(containers)} items on page {page_num}", level=logging.INFO)

            if not containers:
                logger.log("No items found on this page, might be last page", level=logging.INFO)
                break

            # Extract main data from containers
            for c in containers:
                item = {}
                
                # Extract main page data
                for key, selector in config["fields"].items():
                    try:
                        if isinstance(selector, dict):
                            elem = c.find_element(By.CSS_SELECTOR, selector["selector"])
                            item[key] = elem.get_attribute(selector["attribute"])
                            
                            # If this is the link field, store it for later subpage scraping
                            if selector.get("is_link", False):
                                item["_temp_link"] = item[key]  # Store link with temporary key
                        else:
                            elem = c.find_element(By.CSS_SELECTOR, selector)
                            item[key] = elem.text.strip()
                            logger.log(f"Extracted '{key}': {item[key]}", level=logging.INFO)
                    except Exception as e:
                        item[key] = None
                        logger.log(f"Couldn't extract '{key}': {e}", level=logging.WARNING)
                
                results.append(item)
            
            # Check if we should continue to next page
            if not config.get("paginate", False):
                break
            
            # Stop if we've reached total pages
            if total_pages and page_num >= total_pages:
                logger.log(f"Reached the last page ({total_pages})", level=logging.INFO)
                break
            
            # Handle pagination based on type
            if is_url_based:
                success, next_url = handle_url_based_pagination(driver, driver.current_url, page_num)
                if not success:
                    logger.log("URL-based pagination ended", level=logging.INFO)
                    break
            else:
                if not handle_click_based_pagination(driver, config["next_page_selector"], page_num):
                    logger.log("Click-based pagination ended", level=logging.INFO)
                    break
            
            page_num += 1
            time.sleep(config.get("page_wait", 5))

        # Phase 2: Process subpages if configured
        if config.get("scrape_subpages", False):
            logger.log("\nPhase 2: Processing subpages...", level=logging.INFO)
            total_items = len(results)
            
            for index, item in enumerate(results, 1):
                if item.get("_temp_link"):
                    logger.log(f"Processing subpage {index}/{total_items}: {item['_temp_link']}", level=logging.INFO)
                    subpage_data = scrape_subpage(driver, config, item["_temp_link"])
                    item.update(subpage_data)
                    del item["_temp_link"]  # Remove temporary link field
                    time.sleep(config.get("subpage_wait", 3))  # Wait between subpage requests

        # Add delays for concurrent scraping throughout the process
        if config.get("concurrent"):
            request_delay = config.get("request_delay", 1)
            
            # Add delay between page navigations
            if config.get("paginate", False):
                time.sleep(request_delay)
            
            # Add delay between subpage scraping
            if config.get("scrape_subpages", False):
                time.sleep(request_delay)
                
        # Save results to output files
        # Set default output directory and filenames if not provided or empty
        output_dir = config.get("output_dir", "backend/output/default")
        if not output_dir:
            output_dir = "backend/output/default"
            
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate default output filenames if not provided or empty
        output_json = config.get("output_json", "")
        if not output_json:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_json = os.path.join(output_dir, f"results_{timestamp}.json")
        elif not os.path.isabs(output_json) and not os.path.dirname(output_json):
            # If only filename is provided without directory
            output_json = os.path.join(output_dir, output_json)
            
        output_excel = config.get("output_excel", "")
        if not output_excel:
            timestamp = time.strftime("%Y%m%d_%H%M%S") 
            output_excel = os.path.join(output_dir, f"results_{timestamp}.xlsx")
        elif not os.path.isabs(output_excel) and not os.path.dirname(output_excel):
            # If only filename is provided without directory
            output_excel = os.path.join(output_dir, output_excel)
            
        # Ensure output file directories exist
        os.makedirs(os.path.dirname(output_json), exist_ok=True)
        os.makedirs(os.path.dirname(output_excel), exist_ok=True)
        
        # Save the data
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=4)
        pd.DataFrame(results).to_excel(output_excel, index=False)

        logger.log(f"\n[SUCCESS] Scraping complete. {len(results)} items saved.", level=logging.INFO)
        logger.log(f"Results saved to JSON: {output_json}", level=logging.INFO)
        logger.log(f"Results saved to Excel: {output_excel}", level=logging.INFO)
        logger.log("Scraper completed successfully", level=logging.INFO)

        # Cleanup driver after successful completion
        if driver is not None:
            logger.log("Cleaning up driver after successful scraping...", level=logging.INFO)
            try:
                # Try to close the browser window first
                try:
                    driver.close()
                    logger.log("Successfully closed browser window", level=logging.INFO)
                except Exception as e:
                    logger.log(f"Error closing browser window: {e}", level=logging.WARNING)
                
                # Then try to quit the driver
                try:
                    driver.quit()
                    logger.log("Successfully quit driver", level=logging.INFO)
                except Exception as e:
                    logger.log(f"Error quitting driver: {e}", level=logging.WARNING)
                
                # Force cleanup of any remaining processes
                try:
                    import psutil
                    chrome_processes_killed = 0
                    for proc in psutil.process_iter(['pid', 'name']):
                        try:
                            if 'chrome' in proc.info['name'].lower():
                                proc.kill()
                                chrome_processes_killed += 1
                        except:
                            pass
                    if chrome_processes_killed > 0:
                        logger.log(f"Killed {chrome_processes_killed} remaining Chrome processes", level=logging.INFO)
                except Exception as e:
                    logger.log(f"Error during process cleanup: {e}", level=logging.WARNING)
                
                driver = None  # Clear the driver reference
            except Exception as e:
                logger.log(f"Error during driver cleanup: {e}", level=logging.ERROR)
                
        return

    except Exception as e:
        logger.log(f"[ERROR] Scraping failed: {e}", level=logging.ERROR)
        import traceback
        logger.log(traceback.format_exc(), level=logging.ERROR)
        raise  # Re-raise the exception to be handled by the server
    finally:
        # Final cleanup in case of any errors
        if driver is not None:
            logger.log("Performing final driver cleanup...", level=logging.INFO)
            try:
                # Try to close the browser window first
                try:
                    driver.close()
                    logger.log("Successfully closed browser window in cleanup", level=logging.INFO)
                except Exception as e:
                    logger.log(f"Error closing browser window in cleanup: {e}", level=logging.WARNING)
                
                # Then try to quit the driver
                try:
                    driver.quit()
                    logger.log("Successfully quit driver in cleanup", level=logging.INFO)
                except Exception as e:
                    logger.log(f"Error quitting driver in cleanup: {e}", level=logging.WARNING)
                
                # Force cleanup of any remaining processes
                try:
                    import psutil
                    chrome_processes_killed = 0
                    for proc in psutil.process_iter(['pid', 'name']):
                        try:
                            if 'chrome' in proc.info['name'].lower():
                                proc.kill()
                                chrome_processes_killed += 1
                        except:
                            pass
                    if chrome_processes_killed > 0:
                        logger.log(f"Killed {chrome_processes_killed} remaining Chrome processes in cleanup", level=logging.INFO)
                except Exception as e:
                    logger.log(f"Error during process cleanup in cleanup: {e}", level=logging.WARNING)
            except Exception as e:
                logger.log(f"Error during final driver cleanup: {e}", level=logging.ERROR)
            finally:
                driver = None  # Always clear the driver reference
        
        # Close job-specific log file if it exists
        if config.get("log_file"):
            try:
                for handler in logger.logger.handlers[:]:
                    if isinstance(handler, logging.FileHandler) and handler.baseFilename == config["log_file"]:
                        try:
                            handler.flush()  # Ensure all data is written
                            handler.close()  # Close the handler
                        except Exception as e:
                            logger.log(f"Error closing log handler: {e}", level=logging.WARNING)
                        finally:
                            logger.logger.removeHandler(handler)  # Remove the handler regardless of close success
            except Exception as e:
                logger.log(f"Error during log file cleanup: {e}", level=logging.WARNING)

def main():
    parser = argparse.ArgumentParser(description='Web Scraper')
    parser.add_argument('--config', required=True, help='Path to config file')
    args = parser.parse_args()
    
    # Load configuration
    with open(args.config, 'r', encoding='utf-8') as f:
        global config
        config = json.load(f)
    
    # Add file handler if log file is specified
    if config.get('log_file'):
        logger.add_file_handler(config['log_file'])
    
    # Log start message
    logger.log(f"Starting scraper with configuration:")
    for key, value in config.items():
        if key not in ['fields', 'subpage_fields']:
            logger.log(f"{key}: {value}")
    
    # Run scraper
    if validate_config(config):
        scrape_data(config)
    else:
        logger.log("Invalid configuration", level=logging.ERROR)
        sys.exit(1)

if __name__ == '__main__':
    main()
