# Parsera n8n Service

Self-hosted HTTP service that wraps the Python `parsera` library behind a simple HTTP API.

The service runs Parsera and Playwright Chromium inside the same container.

No Browserless service is required.  
No Firefox browser is installed or used.

## Features

- FastAPI HTTP API
- `GET /health`
- `POST /scrape`
- Parsera-based extraction
- Internal Playwright Chromium browser
- Custom LLM support via LangChain provider packages
- Supported LLM providers:
  - Parsera API
  - Gemini
  - OpenAI
  - Ollama
- Docker Compose ready
- n8n compatible
- Can also be used without n8n
- Runtime limits for URL length, extraction rule length and scroll count

## Architecture

```text
Client, n8n or another HTTP caller
  |
  | HTTP POST /scrape
  v
Parsera n8n Service
  |
  | internal Python call
  v
Parsera
  |
  | internal Playwright
  v
Chromium inside the same container
