"""Verify real discovery/search/read without an LLM or a running web server."""
import json
from datetime import timedelta

import anyio
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from app.agents.repository import RepositoryStore
from app.mcp_client import MCPGateway, server_parameters
from app.mcp_contract import TOOLS


async def smoke():
    parameters, expected = server_parameters(RepositoryStore())
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=5)) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            assert TOOLS == {tool.name for tool in listed.tools}
            gateway = MCPGateway(session, expected, [])
            description = await gateway.call("describe_repository", {})
            search = await gateway.call("search_code", {"terms": ["requireApiKey"], "limit": 2})
            assert search["hits"]
            hit = search["hits"][0]
            snippet = await gateway.call("read_file", {"path": hit["file"]["path"], "line": max(1, hit["line"] - 3), "limit": 18})
            assert snippet["source"]["commit_sha"] == expected
            print(json.dumps({"status": "ok", "server": initialized.serverInfo.name, "transport": "stdio",
                              "tools": sorted(TOOLS), "commit_sha": expected,
                              "indexed_files": description["info"]["indexed_files"],
                              "sample_citation": snippet["source"]["url"]}, indent=2))


if __name__ == "__main__":
    anyio.run(smoke)
