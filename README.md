# Parsera n8n Service

Self-hosted HTTP service that wraps the Python `parsera` library and exposes it through a small FastAPI API.

The container runs:

- FastAPI HTTP API
- Parsera
- Playwright Chromium inside the same container
- Optional LLM providers:
  - Parsera API
  - Gemini
  - OpenAI
  - Ollama

No Browserless service is required.  

---

## Endpoints

The container exposes two HTTP endpoints:

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/health` | Checks service status and configuration |
| `POST` | `/scrape` | Scrapes a URL using Parsera and returns extracted data. See Parsera doc for JSON structure|
