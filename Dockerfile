# Use Python 3.9 as base image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies including X11
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    gawk \
    xvfb \
    x11vnc \
    xterm \
    fluxbox \
    libgconf-2-4 \
    libnss3 \
    libfontconfig1 \
    libxss1 \
    libasound2 \
    libxtst6 \
    libxi6 \
    default-jdk \
    novnc \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Install ChromeDriver
RUN CHROME_VERSION=$(google-chrome --version | awk '{print $3}') \
    && echo "Chrome version: $CHROME_VERSION" \
    && CHROMEDRIVER_VERSION=$(curl -s "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_$(echo $CHROME_VERSION | cut -d'.' -f1)") \
    && echo "ChromeDriver version: $CHROMEDRIVER_VERSION" \
    && wget -q "https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/$CHROMEDRIVER_VERSION/linux64/chromedriver-linux64.zip" \
    && unzip chromedriver-linux64.zip -d /usr/local/bin \
    && mv /usr/local/bin/chromedriver-linux64/chromedriver /usr/local/bin/ \
    && rm -rf chromedriver-linux64.zip /usr/local/bin/chromedriver-linux64 \
    && chmod +x /usr/local/bin/chromedriver

# Create necessary directories
RUN mkdir -p /app/drivers /app/output /app/temp /app/logs /app/data

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=server.py
ENV FLASK_ENV=production
ENV CHROME_BIN=/usr/bin/google-chrome
ENV CHROMEDRIVER_PATH=/usr/local/bin/chromedriver
ENV DISPLAY=:99
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV FRONTEND_URL=https://webscraper-frontend-b3gmeeckhue2b3fz.canadacentral-01.azurewebsites.net
ENV ALLOWED_ORIGINS=https://webscraper-frontend-b3gmeeckhue2b3fz.canadacentral-01.azurewebsites.net
ENV DOCKER_CONTAINER=true

# Expose the port the app runs on
EXPOSE 5000

# Start Xvfb and run the application
CMD Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 & \
    fluxbox & \
    x11vnc -display :99 -forever -nopw -quiet & \
    gunicorn --bind 0.0.0.0:5000 --worker-class eventlet --workers 1 server:app 