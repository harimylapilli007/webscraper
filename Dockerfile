# Build stage
FROM python:3.9-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies in a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.9-slim

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    xvfb \
    libxi6 \
    libgconf-2-4 \
    fonts-liberation \
    libappindicator1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxss1 \
    libxtst6 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome and ChromeDriver
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Install ChromeDriver (using a fixed version for stability)
RUN CHROMEDRIVER_VERSION=114.0.5735.90 \
    && wget -q "https://chromedriver.storage.googleapis.com/$CHROMEDRIVER_VERSION/chromedriver_linux64.zip" \
    && unzip chromedriver_linux64.zip -d /usr/local/bin \
    && rm chromedriver_linux64.zip \
    && chmod +x /usr/local/bin/chromedriver

# Create necessary directories and set permissions
RUN mkdir -p /home/chrome/.config/google-chrome \
    && mkdir -p /app/output /app/logs /app/data /app/temp \
    && chown -R appuser:appuser /home/chrome \
    && chown -R appuser:appuser /app \
    && chmod -R 777 /app/output /app/logs /app/data /app/temp

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY . .

# Switch to non-root user
USER appuser

# Expose the port the app runs on
EXPOSE 5000

# Set environment variables
ENV DISPLAY=:99
ENV CHROME_BIN=/usr/bin/google-chrome
ENV CHROME_PATH=/usr/lib/chromium-browser/
ENV CHROMEDRIVER_PATH=/usr/local/bin/chromedriver
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV GUNICORN_CMD_ARGS="--access-logfile=- --error-logfile=- --log-level=debug --capture-output --enable-stdio-inheritance"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Command to run the application with optimized WebSocket settings
CMD ["gunicorn", \
    "--worker-class", "threads", \
    "-w", "4", \
    "--threads", "4", \
    "--timeout", "120", \
    "--keep-alive", "60", \
    "--max-requests", "1000", \
    "--max-requests-jitter", "50", \
    "--worker-connections", "1000", \
    "--backlog", "2048", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "--log-level", "debug", \
    "--capture-output", \
    "--enable-stdio-inheritance", \
    "--reload", \
    "server:app", \
    "--bind", "0.0.0.0:5000"] 