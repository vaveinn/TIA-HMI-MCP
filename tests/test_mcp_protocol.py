"""Speak real MCP over stdio to the server, exactly as a client would.

Spawns server.py, does the initialize handshake, lists the tools and calls
tia_status. Proves the protocol path, not just the underlying functions.

It drives a live TIA Portal and ends with tia_disconnect(save=False), so it
closes the open project and throws away unsaved changes.

Run:  .venv/Scripts/python.exe test_mcp_protocol.py
"""


# Allow running this file directly from any working directory.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import subprocess
import threading

PYTHON = sys.executable
SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.py")
PROJECT_PATH = os.environ.get("TIA_PROJECT_PATH") or (sys.argv[1] if len(sys.argv) > 1 else "")


def main() -> int:
    process = subprocess.Popen(
        [PYTHON, SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    errors: list[str] = []

    def drain_stderr() -> None:
        for line in process.stderr:
            errors.append(line.rstrip())

    threading.Thread(target=drain_stderr, daemon=True).start()

    def send(payload: dict) -> None:
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()

    def receive(request_id: int, timeout_lines: int = 200) -> dict:
        """Read until the response carrying request_id comes back."""
        for _ in range(timeout_lines):
            line = process.stdout.readline()
            if not line:
                raise RuntimeError("server closed stdout")
            line = line.strip()
            if not line:
                continue
            message = json.loads(line)
            if message.get("id") == request_id:
                return message
        raise RuntimeError(f"no response for id {request_id}")

    try:
        send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "protocol-probe", "version": "1.0"},
            },
        })
        init = receive(1)
        server_info = init.get("result", {}).get("serverInfo", {})
        print(f"initialize      -> protocolVersion={init.get('result', {}).get('protocolVersion')}")
        print(f"                   serverInfo={server_info}")

        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listing = receive(2)
        tools = listing.get("result", {}).get("tools", [])
        print(f"tools/list      -> {len(tools)} tools")
        for tool in tools:
            print(f"                   {tool['name']}")

        calls = [
            (3, "tia_status", {}),
            (4, "tia_screen_item_types", {}),
            (5, "tia_connect", {"project_path": PROJECT_PATH, "mode": "without_ui"}),
            (6, "tia_list_devices", {}),
            (7, "tia_list_screens", {}),
            (8, "tia_describe", {"path": "screens", "include_values": True}),
            (9, "tia_check_layout", {}),
            (10, "tia_list_panel_models", {}),
            (11, "tia_disconnect", {"save": False}),
        ]

        failures = 0
        for request_id, name, arguments in calls:
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            })
            response = receive(request_id)
            result = response.get("result", {})
            blocks = result.get("content", [])
            text = "\n".join(block.get("text", "") for block in blocks)
            flag = "isError" if result.get("isError") else "ok"
            if result.get("isError"):
                failures += 1
            print(f"\ntools/call {name} -> {flag}")
            print("   " + text.replace("\n", "\n   ")[:900])
        return 1 if failures else 0
    finally:
        process.stdin.close()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        if errors:
            print("\nserver stderr:")
            for line in errors[:10]:
                print("   " + line)


if __name__ == "__main__":
    sys.exit(main())
