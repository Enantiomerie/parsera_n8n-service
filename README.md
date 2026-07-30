# Parsera n8n Service

Self-hosted FastAPI service for n8n that wraps `raznem/parsera` and uses Playwright internally for web scraping plus a configurable LangChain LLM for extraction.

This branch replaces the old Browserless architecture. Browserless is no longer required.

## Features

- Uses `raznem/parsera` directly
- Uses Playwright inside the service container
- Supports Gemini, OpenAI and Ollama through LangChain
- Simple HTTP API for n8n
- Docker Compose deployment
- Non-root runtime user
- Health check endpoint

## Architecture

```text
n8n
  |
  | HTTP POST /scrape
  v
Parsera n8n Service
  |
  | internal Playwright browser automation
  v
Target website
  |
  | extracted page content
  v
LangChain LLM provider
  |
  | structured result
  v
n8n
