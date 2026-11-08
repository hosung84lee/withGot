"""MCP 서버. 실행: uv run python -m mcp_server.server"""

from mcp.server.mcpserver import MCPServer

from backend.db import init_db
from backend.storage import list_documents

mcp = MCPServer("withGod")


@mcp.tool()
def list_uploaded_documents() -> list[dict]:
    """업로드된 문서 목록을 반환합니다."""
    return [d.model_dump() for d in list_documents()]


if __name__ == "__main__":
    init_db()
    mcp.run()
