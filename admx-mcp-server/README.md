# ADMX Policy MCP Server

MCP Server for searching and retrieving Windows Group Policy (ADMX) definitions.
Supports English and Hebrew UI responses.

שרת MCP לחיפוש והצגת הגדרות Group Policy של Windows.
תומך בתגובות בעברית ובאנגלית.

## Features / תכונות

| Tool | Description | תיאור |
|------|-------------|-------|
| `search_policies` | Full-text search | חיפוש טקסט מלא |
| `get_policy_by_key` | Find by registry key | חיפוש לפי מפתח רישום |
| `get_policy_by_name` | Get policy by name | חיפוש לפי שם |
| `list_categories` | List all categories | הצגת קטגוריות |
| `get_policies_by_category` | Policies in category | מדיניויות בקטגוריה |
| `get_database_stats` | Database statistics | סטטיסטיקות |
| `search_by_registry_value` | Find by value name | חיפוש לפי ערך |
| `get_policy_full_details` | Full policy details | פרטים מלאים |

## Quick Start with Open WebUI

### Option 1: Docker Compose (Recommended)

```bash
cd /Users/guylavian/admx-test/admx-mcp-server
docker-compose up -d
```

This starts:
- **ADMX MCP Server** at http://localhost:8001
- **Open WebUI** at http://localhost:3000

### Option 2: Manual Setup

1. **Start the mcpo proxy:**
```bash
cd /Users/guylavian/admx-test/admx-mcp-server
./start_mcpo.sh
```

2. **Access the API:**
- API Docs: http://localhost:8000/admx-policies/docs
- OpenAPI Schema: http://localhost:8000/admx-policies/openapi.json

3. **Configure Open WebUI:**
   - Go to Settings → Tools → OpenAPI Tools
   - Add new tool with URL: `http://localhost:8000/admx-policies`

## Open WebUI Configuration

### Adding the Tool in Open WebUI

1. Open WebUI at http://localhost:3000 (or your instance URL)
2. Navigate to **Workspace** → **Tools** → **Add Tool**
3. Select **OpenAPI Tool**
4. Enter the URL: `http://host.docker.internal:8001/admx-policies` (if using Docker)
   Or: `http://localhost:8000/admx-policies` (if running locally)
5. Click **Save**

### Using the Tools

In any chat, the LLM can now use the ADMX tools:

**Example prompts:**
- "Search for BitLocker policies"
- "What registry key controls Windows Update?"
- "List all Windows Defender categories"
- "Get database stats in Hebrew"

## API Endpoints

Base URL: `http://localhost:8000/admx-policies`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/search_policies` | Search policies by text |
| POST | `/get_policy_by_key` | Find by registry key |
| POST | `/get_policy_by_name` | Get policy by name |
| POST | `/list_categories` | List categories |
| POST | `/get_policies_by_category` | Get category policies |
| POST | `/get_database_stats` | Get statistics |
| POST | `/search_by_registry_value` | Search by value name |
| POST | `/get_policy_full_details` | Get full details |

### Example API Call

```bash
curl -X POST "http://localhost:8000/admx-policies/search_policies" \
  -H "Content-Type: application/json" \
  -d '{"query": "BitLocker", "lang": "en", "max_results": 5}'
```

### Hebrew Response

```bash
curl -X POST "http://localhost:8000/admx-policies/get_database_stats" \
  -H "Content-Type: application/json" \
  -d '{"lang": "he"}'
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ADMX_DB_PATH` | Path to ADMX JSON database | `../ms-admx-dictionary.json` |

## Files

```
admx-mcp-server/
├── server.py              # MCP server implementation
├── mcpo_config.json       # mcpo configuration (local)
├── mcpo_config_docker.json # mcpo configuration (Docker)
├── start_mcpo.sh          # Local startup script
├── Dockerfile             # Docker image
├── docker-compose.yml     # Full stack with Open WebUI
├── pyproject.toml         # Python package config
└── README.md              # This file
```

## Data Statistics

- **Total Policies:** 3,580
- **ADMX Files:** 230
- **Categories:** 381
- **Source:** Windows 11 24H2 Administrative Templates

## Generating ADMX Database

To regenerate the policy database from ADMX files:

```powershell
# On Windows with ADMX files
./Export-ADMXtoJSON.ps1 -ADMXPath "C:\Windows\PolicyDefinitions" -OutputPath "./ms-admx-dictionary.json"

# Or with custom ADMX path
./Export-ADMXtoJSON.ps1 -ADMXPath "./PolicyDefinitions" -Language "en-US"
```

## Troubleshooting

### mcpo not connecting
- Check that the ADMX_DB_PATH environment variable is set correctly
- Ensure the JSON file exists and is readable

### Open WebUI can't reach the API
- If using Docker, use `host.docker.internal` instead of `localhost`
- Check that port 8000 (or 8001 with Docker Compose) is not blocked

### Hebrew text not displaying correctly
- Ensure your terminal/browser supports UTF-8
- The API returns proper UTF-8 encoded Hebrew text

## License

MIT
