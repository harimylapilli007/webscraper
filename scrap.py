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
import subprocess
from selenium.webdriver.common.action_chains import ActionChains

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
        # Get Chrome version if not provided
        if not version:
            chrome_version = get_chrome_version()
            if chrome_version:
                version = get_compatible_chromedriver_version(chrome_version)
            else:
                # Use latest stable version as fallback
                version = "136.0.7103.93"  # Updated to match your Chrome version
        
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
        
        # List of possible download URLs to try
        download_urls = [
            f"https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/{version}/{platform_name}/chromedriver-{platform_name}.zip",
            f"https://storage.googleapis.com/chrome-for-testing-public/{version}/{platform_name}/chromedriver-{platform_name}.zip",
            f"https://chromedriver.storage.googleapis.com/{version}/chromedriver_{platform_name}.zip"
        ]
        
        # Try each URL until one works
        for url in download_urls:
            try:
                logger.log(f"Trying to download from: {url}", level=logging.INFO)
                response = requests.get(url, timeout=30)
                if response.status_code == 200:
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
                else:
                    logger.log(f"Failed to download from {url}, status code: {response.status_code}", level=logging.WARNING)
            except Exception as e:
                logger.log(f"Error downloading from {url}: {str(e)}", level=logging.WARNING)
                continue
        
        # If all URLs fail, try to get the latest version
        logger.log("All download attempts failed, trying to get latest version...", level=logging.WARNING)
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            driver_path = ChromeDriverManager().install()
            logger.log(f"Successfully installed latest ChromeDriver using webdriver_manager: {driver_path}", level=logging.INFO)
            return driver_path
        except Exception as e:
            logger.log(f"Failed to install latest version: {str(e)}", level=logging.ERROR)
            raise Exception("Failed to download ChromeDriver from all sources")
    
    except Exception as e:
        logger.log(f"Failed to download ChromeDriver manually: {str(e)}", level=logging.ERROR)
        return None

def get_chrome_version():
    """Get the installed Chrome version."""
    try:
        # Try different methods to get Chrome version
        if platform.system() == "Windows":
            # Method 1: Try registry
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon")
                version, _ = winreg.QueryValueEx(key, "version")
                logger.log(f"Detected Chrome version from registry: {version}", level=logging.INFO)
                return version
            except:
                pass

            # Method 2: Try program files
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
            ]
            
            for path in chrome_paths:
                if os.path.exists(path):
                    try:
                        version = subprocess.check_output([path, '--version']).decode('utf-8')
                        version = version.split()[2]  # Get the version number
                        logger.log(f"Detected Chrome version from binary: {version}", level=logging.INFO)
                        return version
                    except:
                        continue
        else:
            # For Linux/Mac
            chrome_bin = os.environ.get('CHROME_BIN', '/usr/bin/google-chrome')
            if os.path.exists(chrome_bin):
                version = subprocess.check_output([chrome_bin, '--version']).decode('utf-8')
                version = version.split()[2]  # Get the version number
                logger.log(f"Detected Chrome version: {version}", level=logging.INFO)
                return version

        logger.log("Could not detect Chrome version automatically", level=logging.WARNING)
        return None
    except Exception as e:
        logger.log(f"Error detecting Chrome version: {str(e)}", level=logging.WARNING)
        return None

def get_compatible_chromedriver_version(chrome_version):
    """Return a compatible ChromeDriver version based on Chrome version."""
    try:
        # Extract major version number
        match = re.match(r'^(\d+)\.', chrome_version)
        if match:
            chrome_major = match.group(1)
            logger.log(f"Chrome major version: {chrome_major}", level=logging.INFO)
            
            # For Chrome 115 and above, use the same version
            if int(chrome_major) >= 115:
                return chrome_version
            
            # For older versions, use the version mapping
            version_map = {
                "114": "114.0.5735.90",
                "113": "113.0.5672.63",
                "112": "112.0.5615.49",
                "111": "111.0.5563.64",
                "110": "110.0.5481.77",
                "109": "109.0.5414.74",
                "108": "108.0.5359.71",
                "107": "107.0.5304.62",
                "106": "106.0.5249.61",
                "105": "105.0.5195.52",
                "104": "104.0.5112.79",
                "103": "103.0.5060.53",
                "102": "102.0.5005.61",
                "101": "101.0.4951.41",
                "100": "100.0.4896.60",
                "99": "99.0.4844.51",
                "98": "98.0.4758.102",
                "97": "97.0.4692.71",
                "96": "96.0.4664.45",
                "95": "95.0.4638.69",
                "94": "94.0.4606.61",
                "93": "93.0.4577.63",
                "92": "92.0.4515.107",
                "91": "91.0.4472.124"
            }
            
            if chrome_major in version_map:
                return version_map[chrome_major]
            
        # If no match found, return the same version as Chrome
        logger.log(f"No specific mapping found, using Chrome version: {chrome_version}", level=logging.INFO)
        return chrome_version
    except Exception as e:
        logger.log(f"Error getting compatible ChromeDriver version: {str(e)}", level=logging.WARNING)
        return chrome_version

def setup_driver(headless=True):
    """Initialize and return a Chrome WebDriver instance."""
    try:
        # Set up Chrome options
        chrome_options = Options()
        
        # Check if running in Docker or Azure (no display server)
        is_containerized = os.environ.get('DOCKER_CONTAINER') == 'true' or os.environ.get('AZURE_WEBSITE_INSTANCE_ID') is not None
        
        # If in containerized environment, use Xvfb display
        if is_containerized:
            display = os.environ.get('DISPLAY', ':99')
            logger.log(f"Running in containerized environment with display {display}", level=logging.INFO)
            # Add container-specific options
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--start-maximized')
        
        # Common Chrome options
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-software-rasterizer')
        
        # Add user agent
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.93 Safari/537.36')

        # Get Chrome version
        chrome_version = get_chrome_version()
        if not chrome_version:
            raise Exception("Could not detect Chrome version")

        logger.log(f"Detected Chrome version: {chrome_version}", level=logging.INFO)

        try:
            # Try using webdriver_manager with latest version
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service as ChromeService
            
            # Install ChromeDriver using webdriver_manager
            driver_path = ChromeDriverManager().install()
            logger.log(f"Installed ChromeDriver at: {driver_path}", level=logging.INFO)
            
            # Create service with the installed driver
            service = ChromeService(executable_path=driver_path)
            
            # Initialize the driver with retry logic
            max_retries = 3
            retry_count = 0
            while retry_count < max_retries:
                try:
                    driver = webdriver.Chrome(service=service, options=chrome_options)
                    driver.set_page_load_timeout(30)
                    driver.implicitly_wait(10)
                    
                    # Verify ChromeDriver version matches Chrome version
                    driver_version = driver.capabilities['chrome']['chromedriverVersion'].split()[0]
                    logger.log(f"ChromeDriver version: {driver_version}", level=logging.INFO)
                    
                    if not driver_version.startswith(chrome_version.split('.')[0]):
                        raise Exception(f"ChromeDriver version {driver_version} does not match Chrome version {chrome_version}")
                    
                    logger.log("Chrome WebDriver initialized successfully", level=logging.INFO)
                    return driver
                except Exception as e:
                    retry_count += 1
                    logger.log(f"Failed to initialize Chrome WebDriver (attempt {retry_count}/{max_retries}): {str(e)}", level=logging.ERROR)
                    if retry_count == max_retries:
                        raise
                    time.sleep(2)  # Wait before retrying
                    
        except Exception as e:
            logger.log(f"Error using webdriver_manager: {str(e)}", level=logging.ERROR)
            raise Exception("Failed to set up Chrome WebDriver")

    except Exception as e:
        logger.log(f"Error setting up Chrome WebDriver: {str(e)}", level=logging.ERROR)
        raise

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
    
    # Validate skip_pages if provided
    if "skip_pages" in config:
        try:
            skip_pages = int(config["skip_pages"])
            if skip_pages < 0:
                logger.log("skip_pages must be a non-negative integer", level=logging.ERROR)
                return False
            logger.log(f"Will skip {skip_pages} pages before starting to scrape", level=logging.INFO)
        except ValueError:
            logger.log("skip_pages must be a valid integer", level=logging.ERROR)
            return False
    
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
        # Store initial content for comparison
        initial_content = driver.find_elements(By.CSS_SELECTOR, "tr.grid-row")
        initial_content_count = len(initial_content)
        initial_first_item_text = initial_content[0].text if initial_content else ""
        
        # Try multiple times to find and click the next page button
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Wait for next page button to be present and clickable
                next_page = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, next_page_selector))
                )
                
                # Check if next page button is enabled and visible
                if next_page.is_displayed() and next_page.is_enabled():
                    # Store current URL to verify page change
                    old_url = driver.current_url
                    
                    # Scroll button into view with smooth scrolling
                    driver.execute_script("""
                        arguments[0].scrollIntoView({
                            behavior: 'smooth',
                            block: 'center'
                        });
                    """, next_page)
                    time.sleep(2)
                    
                    # Try multiple click methods
                    click_success = False
                    click_methods = [
                        lambda: driver.execute_script("arguments[0].click();", next_page),
                        lambda: next_page.click(),
                        lambda: ActionChains(driver).move_to_element(next_page).click().perform()
                    ]
                    
                    for click_method in click_methods:
                        try:
                            click_method()
                            click_success = True
                            logger.log(f"Successfully clicked next page button using method {click_methods.index(click_method) + 1}", level=logging.INFO)
                            break
                        except Exception as click_error:
                            continue
                    
                    if not click_success:
                        logger.log("All click methods failed", level=logging.WARNING)
                        continue
                    
                    # Wait for page to load and content to change
                    try:
                        # Wait for any of these conditions to be true
                        def page_changed(driver):
                            try:
                                # Check if URL changed
                                if driver.current_url != old_url:
                                    return True
                                
                                # Check if content count changed
                                new_content = driver.find_elements(By.CSS_SELECTOR, "tr.grid-row")
                                if len(new_content) != initial_content_count:
                                    return True
                                
                                # Check if first item text changed
                                if new_content and new_content[0].text != initial_first_item_text:
                                    return True
                                
                                # Check if page number changed in pagination
                                try:
                                    current_page_elem = driver.find_element(By.CSS_SELECTOR, f"{next_page_selector}.active, {next_page_selector}.current")
                                    if current_page_elem and str(current_page + 1) in current_page_elem.text:
                                        return True
                                except:
                                    pass
                                
                                return False
                            except:
                                return False
                        
                        # Wait for page change with increased timeout
                        WebDriverWait(driver, 20).until(page_changed)
                        
                        # Additional wait to ensure content is fully loaded
                        time.sleep(3)
                        
                        # Verify the change
                        new_content = driver.find_elements(By.CSS_SELECTOR, "tr.grid-row")
                        new_content_count = len(new_content)
                        
                        # Log the change details
                        logger.log(f"Content count changed: {initial_content_count} -> {new_content_count}", level=logging.INFO)
                        if new_content:
                            logger.log(f"First item changed: {initial_first_item_text[:50]}... -> {new_content[0].text[:50]}...", level=logging.INFO)
                        
                        # If we have new content or URL changed, consider it successful
                        if new_content_count > 0 or driver.current_url != old_url:
                            logger.log(f"Successfully moved to page {current_page + 1}", level=logging.INFO)
                            return True
                        else:
                            logger.log("Page content did not change after clicking next", level=logging.WARNING)
                            continue
                            
                    except TimeoutException:
                        logger.log("Timeout waiting for page content to change", level=logging.WARNING)
                        # Check if we're actually on a new page despite the timeout
                        if driver.current_url != old_url:
                            logger.log("URL changed despite timeout, considering navigation successful", level=logging.INFO)
                            return True
                        continue
                    
                else:
                    logger.log("Next page button is not enabled or visible", level=logging.INFO)
                    # Try to find the next page number button instead
                    try:
                        next_page_num = driver.find_element(By.CSS_SELECTOR, f"{next_page_selector}:not([disabled])")
                        if next_page_num.is_displayed() and next_page_num.is_enabled():
                            next_page_num.click()
                            time.sleep(3)
                            return True
                    except:
                        pass
                    
                    # If we've tried all attempts and still can't find a working next button
                    if attempt == max_attempts - 1:
                        logger.log("Could not find any working next page button after all attempts", level=logging.WARNING)
                        return False
                    
            except Exception as e:
                logger.log(f"Attempt {attempt + 1} failed: {str(e)}", level=logging.WARNING)
                if attempt == max_attempts - 1:
                    return False
                time.sleep(2)  # Wait before retrying
        
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
                    if selector.get("use_label", False):
                        # Find the label element first
                        label_text = selector.get("label", key)
                        try:
                            # Try to find label by text content
                            label = driver.find_element(By.XPATH, f"//label[contains(text(), '{label_text}')]")
                            
                            # Get the parent form-group div
                            form_group = label.find_element(By.XPATH, "./ancestor::div[contains(@class, 'form-group')]")
                            
                            # Find the value div (usually the next sibling div with col-md-3 class)
                            value_div = form_group.find_element(By.XPATH, ".//div[contains(@class, 'col-md-3')][2]")
                            
                            # Get the text content, excluding any validation spans
                            value = value_div.text.strip()
                            if value:
                                subpage_data[key] = value
                                logger.log(f"Extracted '{key}' using label '{label_text}': {value}", level=logging.INFO)
                            else:
                                subpage_data[key] = None
                                logger.log(f"No value found for label '{label_text}'", level=logging.WARNING)
                                
                        except Exception as label_error:
                            logger.log(f"Couldn't find label '{label_text}': {label_error}", level=logging.WARNING)
                            subpage_data[key] = None
                    else:
                        # Use regular selector method
                        elem = driver.find_element(By.CSS_SELECTOR, selector["selector"])
                        subpage_data[key] = elem.get_attribute(selector["attribute"])
                else:
                    elem = driver.find_element(By.CSS_SELECTOR, selector)
                    subpage_data[key] = elem.text.strip()
                logger.log(f"Extracted subpage field '{key}': {subpage_data[key]}", level=logging.INFO)
            except Exception as e:
                subpage_data[key] = None
                logger.log(f"Couldn't extract subpage field '{key}': {e}", level=logging.WARNING)
        
        return subpage_data
        
    except Exception as e:
        logger.log(f"Failed to scrape subpage {url}: {e}", level=logging.ERROR)
        return {}

def handle_load_more_button(driver, config):
    """Handle dynamic 'Load More' or 'Show More' buttons that appear while scrolling."""
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
            
            # Scroll button into view and highlight it
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_button)
            driver.execute_script("arguments[0].style.border='3px solid red';", load_more_button)
            time.sleep(1)  # Pause to show the highlighted button
            
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
        return 1  # Return error code for invalid config

    logger.log("Starting scraper with configuration:", level=logging.INFO)
    logger.log(json.dumps({k: v for k, v in config.items() if k not in ['fields', 'subpage_fields']}, indent=2), level=logging.INFO)

    driver = None
    try:
        # Validate base URL
        if not config["base_url"].startswith(("http://", "https://")):
            logger.log(f"Invalid base URL: {config['base_url']}. Must start with http:// or https://", level=logging.ERROR)
            return 1

        # Validate container selector
        if not config["container_selector"]:
            logger.log("Container selector is empty", level=logging.ERROR)
            return 1

        # Validate fields
        if not config["fields"]:
            logger.log("No fields defined in configuration", level=logging.ERROR)
            return 1

        # Initialize driver with headless mode disabled
        driver = setup_driver(headless=False)
        if not driver:
            logger.log("Failed to initialize Chrome driver", level=logging.ERROR)
            return 1

        results = []
        page_num = config.get("start_page", 1)
        max_pages = config.get("max_pages", 10)
        skip_pages = config.get("skip_pages", 0)  # Get number of pages to skip
        
        # Set up job-specific logging if configured
        if config.get("log_file"):
            logger.log(f"Job started for user {config.get('user_id')} (Job ID: {config.get('job_id')})", level=logging.INFO)
        
        # Phase 1: Collect all main fields and links
        logger.log("Phase 1: Collecting main fields and links from all pages...", level=logging.INFO)
        try:
            driver.get(config["base_url"])
            logger.log(f"Navigated to base URL: {config['base_url']}", level=logging.INFO)
            
            # Add explicit wait after navigation
            wait_time = config.get("initial_wait", 5)
            logger.log(f"Waiting {wait_time} seconds for page to load...", level=logging.INFO)
            time.sleep(wait_time)
            
        except Exception as e:
            logger.log(f"Failed to navigate to base URL: {str(e)}", level=logging.ERROR)
            return 1
        
        # Add delay for concurrent scraping
        if config.get("concurrent"):
            time.sleep(config.get("request_delay", 1))
        else:
            time.sleep(config.get("initial_wait", 5))
        
        # Verify page loaded successfully
        try:
            WebDriverWait(driver, config.get("initial_wait", 5)).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, config["container_selector"]))
            )
        except TimeoutException:
            logger.log(f"Timeout waiting for container selector '{config['container_selector']}' to appear", level=logging.ERROR)
            return 1
        except Exception as e:
            logger.log(f"Error waiting for container selector: {str(e)}", level=logging.ERROR)
            return 1

        # Get total pages if possible
        if config.get("paginate", False):
            total_pages = get_total_pages(driver, config)
            if total_pages:
                logger.log(f"Total pages to scrape: {min(total_pages, max_pages)}", level=logging.INFO)
        
        # Determine pagination type
        current_url = driver.current_url
        is_url_based = "page/" in current_url or "page=" in current_url

        # Skip pages if configured
        if skip_pages > 0:
            logger.log(f"Skipping {skip_pages} pages...", level=logging.INFO)
            for _ in range(skip_pages):
                if is_url_based:
                    success, next_url = handle_url_based_pagination(driver, driver.current_url, page_num)
                    if not success:
                        logger.log("Failed to skip pages using URL-based navigation", level=logging.ERROR)
                        return 1
                else:
                    if not handle_click_based_pagination(driver, config["next_page_selector"], page_num):
                        logger.log("Failed to skip pages using click-based navigation", level=logging.ERROR)
                        return 1
                page_num += 1
                time.sleep(config.get("page_wait", 5))
            logger.log(f"Successfully skipped {skip_pages} pages. Starting scrape from page {page_num}", level=logging.INFO)
        
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
                    # Smooth scroll animation
                    driver.execute_script("""
                        window.scrollTo({
                            top: document.body.scrollHeight,
                            behavior: 'smooth'
                        });
                    """)
                    time.sleep(config.get("scroll_wait", 3))
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        break
                    last_height = new_height
                    scroll_attempts += 1
            
            # Find all containers
            containers = driver.find_elements(By.CSS_SELECTOR, config["container_selector"])
            if not containers:
                logger.log("No containers found on page. Stopping.", level=logging.WARNING)
                break
            
            logger.log(f"Found {len(containers)} containers on page {page_num}", level=logging.INFO)
            
            # Extract main data from containers
            for c in containers:
                item = {}
                scraping_successful = True
                
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
                        scraping_successful = False
                        logger.log(f"Couldn't extract '{key}': {e}", level=logging.WARNING)
                
                # Only add to results if scraping was successful
                if scraping_successful:
                    results.append(item)
                    logger.log("Successfully added item to results", level=logging.INFO)
                else:
                    logger.log("Skipping item due to failed field extraction", level=logging.WARNING)
            
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
                
        # Only save results if scraping was successful and we have data
        if results:
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
            try:
                with open(output_json, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, indent=4)
                pd.DataFrame(results).to_excel(output_excel, index=False)

                logger.log(f"\n[SUCCESS] Scraping complete. {len(results)} items saved.", level=logging.INFO)
                logger.log(f"Results saved to JSON: {output_json}", level=logging.INFO)
                logger.log(f"Results saved to Excel: {output_excel}", level=logging.INFO)
                logger.log("Scraper completed successfully", level=logging.INFO)
                return 0  # Success
            except Exception as e:
                logger.log(f"Error saving results: {str(e)}", level=logging.ERROR)
                return 1
        else:
            logger.log("\n[ERROR] No data was scraped successfully. No output files were created.", level=logging.ERROR)
            return 1

    except Exception as e:
        logger.log(f"Error during scraping: {str(e)}", level=logging.ERROR)
        if driver:
            driver.quit()
        return 1
    finally:
        if driver:
            driver.quit()

def main():
    parser = argparse.ArgumentParser(description='Web Scraper')
    parser.add_argument('--config', required=True, help='Path to config file')
    args = parser.parse_args()
    
    try:
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
            return_code = scrape_data(config)
            if return_code != 0:
                logger.log(f"Scraper failed with return code {return_code}", level=logging.ERROR)
            sys.exit(return_code)
        else:
            logger.log("Invalid configuration", level=logging.ERROR)
            sys.exit(1)
    except Exception as e:
        logger.log(f"Fatal error in main: {str(e)}", level=logging.ERROR)
        sys.exit(1)

if __name__ == '__main__':
    main()
