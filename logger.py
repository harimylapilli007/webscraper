import logging
import sys
import re

class Logger:
    def __init__(self):
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        # Filter for Chrome driver exception messages
        class ChromeExceptionFilter(logging.Filter):
            def filter(self, record):
                # Skip any log messages about Chrome.__del__ exceptions
                message = record.getMessage()
                
                # Common Chrome driver exception patterns
                chrome_exception_patterns = [
                    "Exception ignored in: <function Chrome.__del__",
                    "OSError: [WinError 6] The handle is invalid",
                    "Traceback (most recent call last):",
                    "File \"undetected_chromedriver\__init__.py\", line",
                    "self.quit()",
                    "time.sleep(0.1)"
                ]
                
                # Check if any pattern appears in the message
                for pattern in chrome_exception_patterns:
                    if pattern in message:
                        return False
                
                return True
        
        # Add filter to the handler
        handler.addFilter(ChromeExceptionFilter())
        self.logger.addHandler(handler)
    
    def log(self, message, level=logging.INFO):
        # Skip Chrome driver exception logs completely
        if isinstance(message, str):
            chrome_exception_patterns = [
                "Exception ignored in: <function Chrome.__del__",
                "OSError: [WinError 6] The handle is invalid",
                "Traceback (most recent call last):",
                "File \"undetected_chromedriver\__init__.py\", line",
                "self.quit()",
                "time.sleep(0.1)"
            ]
            
            for pattern in chrome_exception_patterns:
                if pattern in message:
                    return
        
        # Log normal messages
        self.logger.log(level, message) 