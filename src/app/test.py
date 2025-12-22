import asyncio
from src.app.mcp.mcp_client import MCPClient
from src.app.config.settings import settings

"""
To run this test, execute the following commands in your terminal:
(.venv) rashmi@Rashmis-MacBook-Air notion-play % set -a
(.venv) rashmi@Rashmis-MacBook-Air notion-play % source ./.env
(.venv) rashmi@Rashmis-MacBook-Air notion-play % set +a
(.venv) rashmi@Rashmis-MacBook-Air notion-play % python -m src.app.test
"""

async def main():
    mcp = MCPClient(config_path=settings.mcp_config_path)
    await mcp.connect()
    tools = await mcp.get_tools("notionApi")

    tool_map = {t.name: t for t in tools}

    # 1) Validate token works
    me = await tool_map["notionApi_API-get-self"].ainvoke({})
    print("GET SELF:", me)

    # 2) Search something you know exists in Notion
    res = await tool_map["notionApi_API-post-search"].ainvoke({
        "query": "Notes",
        "filter": {"property": "object", "value": "page"}
    })
    print("SEARCH:", res)

asyncio.run(main())
