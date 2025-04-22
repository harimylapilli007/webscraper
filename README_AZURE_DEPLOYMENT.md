# Azure Deployment Instructions

This application is configured to be deployed to Azure App Service using Gunicorn.

## Prerequisites

- Azure account with active subscription
- Azure CLI installed locally
- Git installed locally

## Environment Setup

The application uses environment variables for configuration. A sample file `.env_sample` is provided with all required variables:

```
# Server Configuration
PORT=8000
DEBUG=False
HOST=0.0.0.0

# CORS Settings
FRONTEND_URL=http://localhost:3000

# WebSocket Configuration
WEBSOCKET_HOST=0.0.0.0
WEBSOCKET_PORT=6789

# Azure App Service Settings
RUNNING_IN_PRODUCTION=true

# Gunicorn Settings (for production)
GUNICORN_WORKERS=4
GUNICORN_THREADS=4
GUNICORN_LOG_LEVEL=info
```

For local development, copy this file to `.env` and adjust the values as needed.

## Deployment Steps

1. Login to Azure:
   ```
   az login
   ```

2. Create a resource group (if not already created):
   ```
   az group create --name web-scraper-resource-group --location eastus
   ```

3. Create an App Service Plan:
   ```
   az appservice plan create --name web-scraper-plan --resource-group web-scraper-resource-group --sku B1 --is-linux
   ```

4. Create a Web App:
   ```
   az webapp create --resource-group web-scraper-resource-group --plan web-scraper-plan --name your-app-name --runtime "PYTHON:3.9" --deployment-local-git
   ```

5. Configure deployment credentials:
   ```
   az webapp deployment user set --user-name <username> --password <password>
   ```

6. Get the deployment URL:
   ```
   az webapp deployment source config-local-git --name your-app-name --resource-group web-scraper-resource-group
   ```

7. Add the Azure remote to your local git repository:
   ```
   git remote add azure <deployment-url-from-previous-step>
   ```

8. Push to Azure:
   ```
   git push azure main
   ```

## Environment Variables

Configure the following environment variables in your Azure App Service:

1. Go to your App Service in the Azure Portal
2. Navigate to Settings > Configuration > Application settings
3. Add the following settings:
   - FRONTEND_URL: The URL of your frontend application
   - WEBSOCKET_HOST: 0.0.0.0
   - RUNNING_IN_PRODUCTION: true
   - GUNICORN_WORKERS: Number of Gunicorn workers (default: CPU count * 2 + 1)
   - GUNICORN_THREADS: Number of threads per worker (default: 4)
   - GUNICORN_LOG_LEVEL: Logging level for Gunicorn (default: info)

## Files Overview

- `requirements.txt`: Contains all dependencies, including Gunicorn
- `wsgi.py`: Entry point for Gunicorn
- `gunicorn.conf.py`: Configuration for Gunicorn
- `Procfile`: Defines the web process for Azure
- `startup.sh`: Script to run when the application starts
- `web.config`: Configuration for Azure App Service
- `.deployment`: Deployment instructions for Azure
- `.azure/config`: Azure CLI configuration
- `.env_sample`: Sample environment variables file

## Troubleshooting

1. Check logs in the Azure Portal:
   - Go to your App Service
   - Navigate to Monitoring > Log stream

2. If the application doesn't start, check:
   - The startup command in the Azure Portal
   - The log files for any errors
   - The environment variables are set correctly 