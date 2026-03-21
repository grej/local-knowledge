"""MCP server for Local Knowledge — SSE (default) or stdio transport via FastMCP."""

import click
from mcp.server.fastmcp import FastMCP

MCP_PORT = 8322

mcp = FastMCP("local-knowledge", host="127.0.0.1", port=MCP_PORT)

# Import tools to register them via decorators
from . import tools  # noqa: F401, E402


@click.command()
@click.option("--stdio", is_flag=True, help="Use stdio transport instead of SSE.")
def main(stdio: bool):
    """Local Knowledge MCP server."""
    mcp.run(transport="stdio" if stdio else "sse")


if __name__ == "__main__":
    main()
