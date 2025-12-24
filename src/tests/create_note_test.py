import asyncio
import json
import os
from datetime import datetime

from src.app.mcp.mcp_client import MCPClient


def _first_text_payload(tool_result):
    """
    MCP adapter returns list of dict parts. We grab the first text part and parse JSON.
    """
    if not tool_result:
        return None
    first = tool_result[0]
    if isinstance(first, dict) and first.get("type") == "text":
        return first.get("text")
    return None


async def main():
    # Make sure env is loaded (run via: source .env && python -m src.app.test)
    if not os.getenv("NOTION_MCP_ACCESS_TOKEN"):
        raise RuntimeError("NOTION_MCP_ACCESS_TOKEN is not set in env")

    mcp = MCPClient(config_path="./mcp_configs/mcp_servers.json")
    await mcp.connect()
    tools = await mcp.get_tools("notionApi")

    tool_map = {t.name: t for t in tools}

    get_self = tool_map["notionApi_API-get-self"]
    search = tool_map["notionApi_API-post-search"]
    create_page = tool_map["notionApi_API-post-page"]

    me = await get_self.ainvoke({})
    print("GET SELF:", me)

    # 1) Find Genie Notes page
    s = await search.ainvoke({"query": "Genie Notes"})
    s_text = _first_text_payload(s)
    s_json = json.loads(s_text) if s_text else {}
    results = s_json.get("results", [])

    if not results:
        raise RuntimeError("Search returned 0 results for 'Genie Notes'")

    genie_page_id = results[0]["id"]
    print("GENIE PAGE ID:", genie_page_id)

    # 2) Create a test note page under Genie Notes
    title = f"Test Note {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
    payload = {
        "parent": {"page_id": genie_page_id},
        "properties": {
            "title": {
                "title": [
                    {"type": "text", "text": {"content": title}}
                ]
            }
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": "Created via MCP test.py"}}
                    ]
                },
            }
        ],
    }

    created = await create_page.ainvoke(payload)
    print("CREATE PAGE RAW:", created)

    created_text = _first_text_payload(created)
    created_json = json.loads(created_text) if created_text else {}
    print("CREATED PAGE ID:", created_json.get("id"))
    print("CREATED URL:", created_json.get("url"))

    # 3) Search again by that title (proof it exists)
    s2 = await search.ainvoke({"query": title})
    print("SEARCH BACK:", s2)


if __name__ == "__main__":
    asyncio.run(main())
