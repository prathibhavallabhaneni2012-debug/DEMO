# Fusion MCP Server

A small MCP (Model Context Protocol) server that wraps Oracle Fusion
ERP/Financials REST APIs as tools — so you can plug **one MCP endpoint**
into AI Agent Studio instead of wiring up a separate BO / external REST
integration for every use case.

Currently exposed tools:

| Tool | Wraps | Purpose |
|---|---|---|
| `get_invoices` | `GET /fscmRestApi/resources/{version}/invoices` | List/search AP (Payables) invoices, with filters and pagination |
| `get_invoice_by_id` | `GET /fscmRestApi/resources/{version}/invoices/{id}` | Get one invoice by its Fusion `InvoiceId` |

Adding more Fusion resources (Purchase Orders, Requisitions, Sales Orders,
etc.) is just a matter of adding another `@mcp.tool()` function in
`server.py` that calls `_fusion_get(...)` with the right resource path —
they all live under the same `fscmRestApi` base path.

## 1. Setup

```bash
cd fusion-mcp-server
python3 -m venv venv
source venv/bin/activate      # on Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```
FUSION_BASE_URL=http://fa-launchpad.oraclepdemos.com
FUSION_API_VERSION=11.13.26.07.0
FUSION_AUTH_MODE=basic
FUSION_USERNAME=hcm_impl10
FUSION_PASSWORD=D^6K7a?q
```

> **Auth note:** Basic Auth (username/password) is the simplest option and
> is fine for dev/test, but **it does not work if MFA is enabled** on the
> account, and Oracle recommends against it for production. If that's your
> situation, set `FUSION_AUTH_MODE=bearer` and supply a `FUSION_BEARER_TOKEN`
> obtained via your OAuth2 / IDCS-OCI IAM client-credentials flow instead.

## 2. Run

```bash
python server.py
```

You should see:

```
INFO:fusion-mcp:Starting Fusion MCP server on http://0.0.0.0:8000/mcp
INFO:     Uvicorn running on http://0.0.0.0:8000
```

The server exposes the MCP endpoint at:

```
http://<host>:8000/mcp/
```

(note the trailing slash — the bare `/mcp` path 307-redirects to `/mcp/`)

## 3. Plug into Agent Studio

In Agent Studio, add a new MCP connector/tool and point it at:

```
http://<host-reachable-from-agent-studio>:8000/mcp/
```

If Agent Studio and this server aren't on the same network, you'll need to
deploy this somewhere reachable (a VM, container service, etc.) and expose
it over HTTPS — for anything beyond local testing, put it behind a reverse
proxy (nginx/Caddy) or a platform like Cloud Run / ECS / Azure Container
Apps, with TLS termination, since credentials will be traveling in the
Authorization header.

## 4. Test locally without Agent Studio

You can sanity-check the server responds correctly with curl:

```bash
curl -i -X POST http://localhost:8000/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

A `200 OK` with a `serverInfo` block in the response body confirms the
server is wired up correctly. From there, an MCP client (or Agent Studio)
will call `tools/list` and `tools/call` to discover and invoke
`get_invoices` / `get_invoice_by_id`.

## Extending: adding another Fusion resource

```python
@mcp.tool()
async def get_purchase_orders(supplier: Optional[str] = None, limit: int = 25) -> dict:
    """Retrieve purchase orders from Oracle Fusion SCM."""
    params = {"limit": limit, "onlyData": "true"}
    if supplier:
        params["q"] = f"Supplier={supplier}"
    return await _fusion_get("purchaseOrders", params=params)
```

Same pattern for requisitions, sales orders, items, etc. — just swap the
resource path and the query params relevant to that resource.

## Security notes

- Don't commit your real `.env` file.
- Prefer `bearer` (OAuth2) auth over `basic` for anything beyond local dev.
- This server currently has no authentication of its own in front of the
  `/mcp` endpoint — if you deploy it somewhere network-reachable, put it
  behind a reverse proxy that requires its own auth/API key, or restrict
  network access, so it isn't an open proxy to your Fusion credentials.
