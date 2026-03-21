"""MCP server for Local Knowledge — stdio transport via FastMCP."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("local-knowledge")

# Import tools to register them via decorators
from . import tools  # noqa: F401, E402


def main():
    mcp.run()


if __name__ == "__main__":
    main()
