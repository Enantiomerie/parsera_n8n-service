<!-- markdownlint-disable -->
# Parsera n8n Service

Production-ready self-hosted web scraping and data extraction service for [n8n](https://n8n.io/) integration. Orchestrates browser automation via [Browserless](https://www.browserless.io/) and LLM-[...]

## Features

- 🌐 **Browser Orchestration**: Leverages Browserless for reliable headless Chrome automation
- 🤖 **Multi-LLM Support**: Works with Gemini, OpenAI, or self-hosted Ollama
- 🔒 **Production-Ready**: Non-root containers, health checks, security hardening
- 📦 **Docker Native**: Multi-stage builds, minimal image size, optimized for Synology
- 🔧 **n8n Integration**: Simple HTTP API, works on shared Docker network
- 📝 **Structured Logging**: JSON logging for monitoring and troubleshooting
- 🛡️ **Graceful Degradation**: Handles Browserless/LLM unavailability gracefully

## Architecture

```
n8n ──(HTTP POST /scrape)──> Parsera ──(HTTP)──> Browserless (Chromium)
                                  │
                                  └──(HTTP/API)──> LLM (Gemini/OpenAI/Ollama)
```

- **Parsera**: FastAPI service that orchestrates requests
- **Browserless**: Headless Chrome browser (Docker Hub: `browserless/chrome`)
- **LLM**: Data extraction engine (configurable)

## Prerequisites

- Docker and Docker Compose
- n8n running on `n8n_net` Docker network
- API credentials for your chosen LLM provider (Gemini, OpenAI, or Ollama)

## Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/Enantiomerie/parsera_n8n-service.git
cd parsera_n8n-service
```

### 2. Create Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# Choose your LLM provider
LLM_PROVIDER=gemini

# For Gemini
GEMINI_API_KEY=your-api-key-here

# Or for OpenAI
# LLM_PROVIDER=openai
# OPENAI_API_KEY=your-api-key-here
# OPENAI_MODEL=gpt-3.5-turbo

# Or for Ollama (self-hosted)
# LLM_PROVIDER=ollama
# OLLAMA_BASE_URL=http://ollama:11434
# OLLAMA_MODEL=llama2
```

### 3. Ensure n8n_net Exists

The compose file expects an external network named `n8n_net`. If it doesn't exist:

```bash
docker network create n8n_net
```

Or add to your n8n docker-compose.yml:

```yaml
networks:
  n8n_net:
    driver: bridge
```

### 4. Deploy

```bash
docker-compose up -d
```

Verify containers are running:

```bash
docker-compose ps
```

### 5. Check Health

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:45.123456",
  "browserless_available": true,
  "llm_configured": true
}
```

## API Usage

### POST /scrape

Extract data from a URL using LLM rules.

**Request:**

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/products",
    "extraction_rules": "Extract all product names, prices, and availability status. Return as JSON array.",
    "wait_selector": ".product-list"
  }'
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | URL to scrape (max 2000 chars) |
| `extraction_rules` | string | Yes | LLM extraction prompt (max 5000 chars) |
| `wait_selector` | string | No | CSS selector to wait for before extraction |

**Response:**

```json
{
  "success": true,
  "data": {
    "products": [
      {"name": "Product A", "price": "$19.99", "available": true},
      {"name": "Product B", "price": "$29.99", "available": false}
    ]
  },
  "error": null,
  "provider": "gemini",
  "processing_time_ms": 2340,
  "timestamp": "2024-01-15T10:30:45.123456"
}
```

**Error Response:**

```json
{
  "success": false,
  "data": null,
  "error": "Failed to fetch content from Browserless",
  "provider": "gemini",
  "processing_time_ms": 1200,
  "timestamp": "2024-01-15T10:30:45.123456"
}
```

### GET /health

Health check endpoint.

**Response:**

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:45.123456",
  "browserless_available": true,
  "llm_configured": true
}
```

## n8n Integration

### Example n8n Workflow

1. **HTTP Request Node**: POST to `http://parsera:8000/scrape`

```json
{
  "url": "{{ $json.url }}",
  "extraction_rules": "Extract title, description, and metadata from this webpage",
  "wait_selector": "article"
}
```

2. **Set Node**: Extract data from response

```json
{
  "extracted_data": "{{ $json.body.data }}"
}
```

### n8n Docker Compose Addition

```yaml
services:
  n8n:
    # ... your existing config ...
    networks:
      - n8n_net

networks:
  n8n_net:
    driver: bridge
```

Then Parsera can be deployed to the same network.

## Environment Variables

### Core Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |
| `SERVICE_NAME` | `parsera` | Service identifier |

### Browserless Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BROWSERLESS_URL` | `http://browserless:3000` | Browserless API endpoint |
| `BROWSERLESS_TIMEOUT` | `30` | Request timeout in seconds |
| `BROWSERLESS_RETRIES` | `1` | Number of retries on timeout |

### LLM Provider Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `gemini` | LLM provider: `gemini`, `openai`, `ollama` |

### Gemini Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | - | Google Gemini API key (required if using Gemini) |

### OpenAI Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | - | OpenAI API key (required if using OpenAI) |
| `OPENAI_MODEL` | `gpt-3.5-turbo` | OpenAI model name |

### Ollama Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `llama2` | Ollama model name |

### Request Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `REQUEST_TIMEOUT` | `60` | HTTP request timeout in seconds |
| `MAX_URL_LENGTH` | `2000` | Maximum URL length |
| `MAX_EXTRACTION_RULES_LENGTH` | `5000` | Maximum extraction rules length |

### Validation

| Variable | Default | Description |
|----------|---------|-------------|
| `VALIDATE_JSON_OUTPUT` | `true` | Validate LLM JSON output |

## Deployment on Synology

### Prerequisites

- Synology NAS with Docker support (Container Manager)
- n8n already running in Docker
- Repository files available (cloned or uploaded to your NAS)

### Steps

1. **Access Container Manager GUI**

   - Open your Synology DSM (DiskStation Manager)
   - Go to **Main Menu** > **Container Manager** (or search for it)
   - This opens the official Synology Container Manager interface

2. **Create External Network (if needed)**

   - In Container Manager, go to **Network** tab
   - Click **Create** to create a new network
   - Name it `n8n_net` and set driver to **Bridge**
   - Click **Create** to confirm

3. **Configure Environment File**

   - On your NAS (using File Station), navigate to your project directory (e.g., `/volume1/docker/parsera_n8n-service`)
   - Copy `.env.example` to `.env`
   - Edit `.env` with your LLM credentials and provider settings
   - Save the file

4. **Create Browserless Container**

   - In Container Manager, go to **Image** tab
   - Click **Add** > **Add from URL**
   - Enter: `browserless/chrome`
   - Click **Create**
   - Once image is downloaded, go to **Container** tab
   - Click **Create** and select the Browserless image
   - Configure:
     - **Container Name**: `browserless`
     - **Network**: Select `n8n_net`
     - **Port Settings**: Map port `3000` (container) to `3000` (host)
   - Click **Advanced Settings** and set **Resource Limits** if needed
   - Click **Create** to start the container

5. **Create Parsera Container**

   - In Container Manager, go to **Image** tab
   - Click **Add** > **Add from URL** or **Create**
   - If building from source:
     - Click **Create** to build from Dockerfile
     - Upload/select the `Dockerfile` from your project directory
     - Name the image `parsera`
     - Wait for build to complete
   - Go to **Container** tab
   - Click **Create** and select the Parsera image
   - Configure:
     - **Container Name**: `parsera`
     - **Network**: Select `n8n_net`
     - **Port Settings**: Map port `8000` (container) to `8000` (host)
     - **Environment Variables**: Click **Add** and input each variable from your `.env` file:
       - `LLM_PROVIDER`
       - `GEMINI_API_KEY` (or appropriate provider key)
       - `BROWSERLESS_URL=http://browserless:3000`
       - Any other relevant variables
   - Click **Advanced Settings**:
     - Enable **Auto-restart** if desired
     - Set resource limits if needed
   - Click **Create** to start the container

6. **Verify Deployment**

   - In Container Manager, go to **Container** tab
   - Verify both `browserless` and `parsera` containers show **Running** status
   - Click on `parsera` container to view logs
   - Check for any error messages

7. **Test Health Endpoint**

   - Open a browser or terminal on a machine on the same network
   - Navigate to: `http://<synology-ip>:8000/health`
   - Should return a JSON response with `"status": "healthy"`

8. **Connect to n8n**

   - In your n8n workflows, reference the Parsera service at: `http://parsera:8000/scrape`
   - If n8n is on the same `n8n_net` network, it can communicate directly
   - See **n8n Integration** section for workflow examples

### Synology Container Manager Tips

- **Monitoring Logs**: Click on a running container, then select **Details** > **Logs** to view real-time output
- **Stopping/Starting**: Select a container and click **Stop** or **Start** in the toolbar
- **Removing Containers**: Right-click a container and select **Delete** (images persist)
- **Environment Variables**: Can be modified by recreating the container with updated values
- **Data Persistence**: This is a stateless service, so no volumes are needed
- **Network Connectivity**: Containers on the same bridge network can communicate using container names as hostnames

## Troubleshooting

### "Browserless connection refused"

**Problem**: Parsera can't reach Browserless

**Solution**:
```bash
# Check Browserless is running (in Container Manager, verify status)
# In container details, check logs for startup errors

# Verify network configuration
# - Both containers should be on the same network (n8n_net)
# - Check Container Manager > Network tab

# Common causes on Synology
# - Network not properly created or selected
# - Browserless container name mismatch
# - Port mapping misconfiguration
```

### "LLM API key not set"

**Problem**: Configuration error on startup

**Solution**:
```
# Verify .env file was properly saved (File Station)
# In Container Manager, verify environment variables are set:
#   - Select Parsera container
#   - Click Details > Environment
#   - Confirm all LLM variables are present

# Recreate container with correct variables:
#   - Stop the container
#   - Delete the container (keep the image)
#   - Create new container with updated environment variables
```

### "LLM returned invalid JSON"

**Problem**: Extraction returned malformed JSON

**Solution**:
- Refine extraction rules to be more specific
- Use simpler extraction targets
- Check Parsera logs in Container Manager > Container > Details > Logs
- Test with different LLM provider

### Logs

View service logs in Synology Container Manager:

```
- Select the container (parsera or browserless)
- Click Details tab
- Select Logs to view real-time output
- Scroll through logs to find errors
```

Or via command line (if you have SSH access):

```bash
# All services (via docker-compose)
docker-compose logs -f

# Specific container via Container Manager CLI
docker logs <container_id>
```

## Building Locally

For development or custom builds:

```bash
# Build image
docker build -t parsera:dev .

# Run for testing
docker run -it --rm \
  -e LLM_PROVIDER=gemini \
  -e GEMINI_API_KEY=your-key \
  -e BROWSERLESS_URL=http://localhost:3000 \
  parsera:dev
```

## Security Considerations

### Container Security

- ✅ Non-root user (UID 1000)
- ✅ Read-only filesystem recommendations (implement in compose if needed)
- ✅ Resource limits (add in docker-compose.yml if needed)
- ✅ Health checks enabled

### API Security

- ⚠️ No built-in authentication (relies on network isolation)
- ✅ Input validation on all endpoints
- ✅ Timeout protections
- ✅ Graceful error handling (no stack traces in responses)

### Recommendations

1. **Network Isolation**: Keep on internal Docker network, don't expose to public internet
2. **API Keys**: 
   - Use environment variables, not hardcoded
   - Rotate periodically
   - Use dedicated API keys with minimal permissions
3. **Logging**: Monitor logs for errors and suspicious activity
4. **Rate Limiting**: Implement in n8n workflows or add reverse proxy
5. **Firewall**: Restrict Docker network access if on shared system

## Performance Tuning

### Browserless Optimization

```yaml
environment:
  CHROME_EXTRA_ARGS: "--disable-gpu --no-sandbox"
```

### Parsera Optimization

```env
# Shorter timeout for faster feedback on unavailable content
BROWSERLESS_TIMEOUT=15

# Reduce retry attempts
BROWSERLESS_RETRIES=0

# Parallelize if using Gunicorn (not default uvicorn)
WORKERS=4
```

### Resource Limits (Add to docker-compose.yml)

```yaml
services:
  parsera:
    deploy:
      resources:
        limits:
          cpus: "1"
          memory: 512M
        reservations:
          cpus: "0.5"
          memory: 256M
```

## Development

### Local Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run locally
uvicorn main:app --reload
```

### Testing

```bash
# Test health endpoint
curl http://localhost:8000/health

# Test scrape endpoint (requires Browserless running)
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://httpbin.org/html",
    "extraction_rules": "Extract the page title"
  }'
```

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file

## Support

For issues, questions, or suggestions:

- 📋 [GitHub Issues](https://github.com/Enantiomerie/parsera_n8n-service/issues)
- 💬 Discussions in GitHub Discussions (if enabled)

## Related Projects

- [Browserless](https://www.browserless.io/) - Headless Chrome as a service
- [n8n](https://n8n.io/) - Workflow automation
- [Parsera](https://www.parsera.org/) - AI-powered data extraction (original library)
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
