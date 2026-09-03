"""
Oracle Fusion MCP Server
=========================
Exposes Oracle Fusion ERP/Financials REST APIs as MCP tools, so they can be
plugged into AI Agent Studio (or any MCP-compatible client) as a single
connector instead of wiring up separate BO integrations / custom REST calls
per use case.

Currently exposed tools:
  - get_invoices: GET /fscmRestApi/resources/{version}/invoices

Add more tools the same way as your needs grow (Purchase Orders, Requisitions,
Sales Orders, etc.) - they all live under the same fscmRestApi base path.

Transport: Streamable HTTP (so this can be reached via a URL, e.g. for
Agent Studio). Run with:

    python server.py

Then point Agent Studio (or any MCP client) at:

    http://<host>:<port>/mcp

Configuration is read from environment variables / a .env file - see
.env.example.
"""

import os
import base64
import logging
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fusion-mcp")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
FUSION_BASE_URL = os.getenv("FUSION_BASE_URL", "").rstrip("/")
logger.warning(f"DEBUG: FUSION_BASE_URL loaded as: '{FUSION_BASE_URL}'")
FUSION_API_VERSION = os.getenv("FUSION_API_VERSION", "11.13.26.07.0")
FUSION_USERNAME = os.getenv("FUSION_USERNAME", "")
FUSION_PASSWORD = os.getenv("FUSION_PASSWORD", "")
FUSION_AUTH_MODE = os.getenv("FUSION_AUTH_MODE", "basic").lower()  # "basic" or "bearer"
FUSION_BEARER_TOKEN = os.getenv("FUSION_BEARER_TOKEN", "")

REQUEST_TIMEOUT_SECONDS = float(os.getenv("FUSION_REQUEST_TIMEOUT", "30"))

if not FUSION_BASE_URL:
    logger.warning(
        "FUSION_BASE_URL is not set. Set it in your .env file, e.g. "
        "https://<instance>.fa.<datacenter>.oraclecloud.com"
    )

mcp = FastMCP(
    "fusion-mcp",
    host="0.0.0.0",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["demo-3z81.onrender.com"],
        allowed_origins=["https://demo-3z81.onrender.com"],
    ),
)


def _auth_header() -> dict:
    """Build the Authorization header based on configured auth mode."""
    if FUSION_AUTH_MODE == "bearer":
        if not FUSION_BEARER_TOKEN:
            raise RuntimeError(
                "FUSION_AUTH_MODE=bearer but FUSION_BEARER_TOKEN is not set."
            )
        return {"Authorization": f"Bearer {FUSION_BEARER_TOKEN}"}

    # default: basic auth
    if not (FUSION_USERNAME and FUSION_PASSWORD):
        raise RuntimeError(
            "FUSION_AUTH_MODE=basic but FUSION_USERNAME/FUSION_PASSWORD are not set. "
            "Note: Basic Auth does not work if MFA is enabled on the account - "
            "use FUSION_AUTH_MODE=bearer with an OAuth2 token instead in that case."
        )
    token = base64.b64encode(
        f"{FUSION_USERNAME}:{FUSION_PASSWORD}".encode("utf-8")
    ).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


async def _fusion_get(resource_path: str, params: Optional[dict] = None) -> dict:
    """Shared helper to call a Fusion REST GET endpoint."""
    if not FUSION_BASE_URL:
        raise RuntimeError(
            "FUSION_BASE_URL is not configured. Set it in your .env file."
        )

    url = f"{FUSION_BASE_URL}/fscmRestApi/resources/{FUSION_API_VERSION}/{resource_path}"
    headers = {
        "Content-Type": "application/json",
        **_auth_header(),
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(url, headers=headers, params=params)

    if response.status_code >= 400:
        raise RuntimeError(
            f"Fusion API request failed ({response.status_code}) for {url}: "
            f"{response.text[:1000]}"
        )

    return response.json()


@mcp.tool()
async def get_receivables_invoices(
    transaction_number: Optional[str] = None,
    customer: Optional[str] = None,
    business_unit: Optional[str] = None,
    q: Optional[str] = None,
    fields: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Retrieve AR (Receivables) invoices from Oracle Fusion.

    Wraps GET /fscmRestApi/resources/{version}/receivablesInvoices.

    Args:
        transaction_number: Filter to a specific invoice/transaction number
            (exact match).
        customer: Filter by bill-to customer name (exact match).
        business_unit: Filter by business unit name (exact match).
        q: Raw Fusion REST query string (Oracle "q" finder syntax), e.g.
           "InvoiceAmount>1000;CurrencyCode=USD". If provided, this is
           combined with any of the convenience filters above using AND.
        fields: Comma-separated list of fields to return, e.g.
           "TransactionNumber,InvoiceAmount,InvoiceDate,BillToCustomerName".
           Reduces payload size - recommended when you only need a few
           columns.
        limit: Max number of invoices to return (default 25).
        offset: Number of invoices to skip, for pagination (default 0).

    Returns:
        The parsed JSON response from Fusion, including the "items" list
        of receivables invoices and pagination metadata (count, hasMore,
        links, etc.).
    """
    filters = []
    if transaction_number:
        filters.append(f"TransactionNumber={transaction_number}")
    if customer:
        filters.append(f"BillToCustomerName={customer}")
    if business_unit:
        filters.append(f"BusinessUnit={business_unit}")
    if q:
        filters.append(q)

    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "onlyData": "true",
    }
    if filters:
        params["q"] = ";".join(filters)
    if fields:
        params["fields"] = fields

    logger.info("Fetching receivables invoices with params: %s", params)
    return await _fusion_get("receivablesInvoices", params=params)


@mcp.tool()
async def get_receivables_invoice_by_id(customer_transaction_id: str) -> dict[str, Any]:
    """Retrieve a single AR invoice from Oracle Fusion by its CustomerTransactionId.

    Wraps GET /fscmRestApi/resources/{version}/receivablesInvoices/{id}.

    Args:
        customer_transaction_id: The Fusion CustomerTransactionId (not the
            human-readable transaction number) of the invoice to retrieve.

    Returns:
        The parsed JSON response from Fusion for that single receivables
        invoice, including header, lines, and installments.
    """
    return await _fusion_get(f"receivablesInvoices/{customer_transaction_id}")


@mcp.tool()
async def get_sales_orders(
    order_number: Optional[str] = None,
    customer: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    fields: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Retrieve sales orders from Oracle Fusion Order Management.

    Wraps GET /fscmRestApi/resources/{version}/salesOrdersForOrderHub.

    Args:
        order_number: Filter to a specific order number (exact match).
        customer: Filter by customer name on the order (exact match).
        status: Filter by order status, e.g. "Awaiting Shipping",
            "Closed", "Draft" (exact match on the status display value).
        q: Raw Fusion REST query string (Oracle "q" finder syntax) for
           anything not covered by the convenience filters above. Combined
           with them using AND if both are provided.
        fields: Comma-separated list of fields to return, e.g.
           "OrderNumber,Status,OrderTotal,CustomerName". Reduces payload
           size - recommended when you only need a few columns.
        limit: Max number of orders to return (default 25).
        offset: Number of orders to skip, for pagination (default 0).

    Returns:
        The parsed JSON response from Fusion, including the "items" list
        of sales orders and pagination metadata (count, hasMore, links).
    """
    filters = []
    if order_number:
        filters.append(f"OrderNumber={order_number}")
    if customer:
        filters.append(f"CustomerName={customer}")
    if status:
        filters.append(f"StatusCode={status}")
    if q:
        filters.append(q)

    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "onlyData": "true",
    }
    if filters:
        params["q"] = ";".join(filters)
    if fields:
        params["fields"] = fields

    logger.info("Fetching sales orders with params: %s", params)
    return await _fusion_get("salesOrdersForOrderHub", params=params)


@mcp.tool()
async def get_sales_order_by_key(order_key: str) -> dict[str, Any]:
    """Retrieve a single sales order from Oracle Fusion by its OrderKey.

    Wraps GET /fscmRestApi/resources/{version}/salesOrdersForOrderHub/{order_key}.

    Args:
        order_key: The Fusion OrderKey uniquely identifying the sales
            order. This is formed as "{SourceOrderSystem}:{SourceOrderId}",
            e.g. "LEG:R13_Sample_Order" - not the human-readable order
            number by itself.

    Returns:
        The parsed JSON response from Fusion for that single sales order,
        including header details, lines, holds, and totals.
    """
    return await _fusion_get(f"salesOrdersForOrderHub/{order_key}")


if __name__ == "__main__":
    # Streamable HTTP transport -> reachable as a URL (e.g. for Agent Studio)
    host = os.getenv("MCP_HOST", "0.0.0.0")
    # Render (and most cloud hosts) assign the port via the PORT env var.
    # Fall back to MCP_PORT (or 8000) for local runs where PORT isn't set.
    port = int(os.getenv("PORT", os.getenv("MCP_PORT", "8000")))
    mcp.settings.host = host
    mcp.settings.port = port
    logger.info("Starting Fusion MCP server on http://%s:%s/mcp", host, port)
    mcp.run(transport="streamable-http")
