# Web Scraper Backend

This is the backend server for the web scraping application.

## Environment Setup

Create a `.env` file in the root of the backend directory with the following variables:

```
# Server Configuration
PORT=5000
DEBUG=False

# CORS Settings
FRONTEND_URL=http://localhost:3000
```

## Installation

1. Set up a Python virtual environment (recommended):

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Running the server

```bash
python server.py
```

The server will start on http://localhost:5000 by default (or the port specified in your .env file). 