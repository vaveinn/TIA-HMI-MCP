"""Smoke test: does the server register its tools and reach Openness?

Run:  .venv/Scripts/python.exe smoke_test.py
"""


# Allow running this file directly from any working directory.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json

import server as mcp_server


async def main() -> int:
    tools = mcp_server.server._tool_manager.list_tools()
    names = sorted(tool.name for tool in tools)
    print(f"registered tools ({len(names)}):")
    for name in names:
        print(f"  {name}")

    print("\n--- tia_status() ---")
    try:
        result = mcp_server.tia_status()
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1

    print("\n--- tia_screen_item_types() ---")
    try:
        print(", ".join(mcp_server.tia_screen_item_types()))
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
