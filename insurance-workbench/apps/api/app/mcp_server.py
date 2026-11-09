from mcp.server.fastmcp import FastMCP

mcp = FastMCP("insurance-workbench")


@mcp.tool()
def get_service_status() -> dict[str, str]:
    """Return development service status; no benefit calculation is implemented yet."""
    return {"status": "development", "calculation": "not_implemented"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
