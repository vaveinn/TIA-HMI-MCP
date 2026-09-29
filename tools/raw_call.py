"""Call one MCP tool and print the raw JSON-RPC response, unfiltered.

Run:  .venv/Scripts/python.exe raw_call.py tia_list_devices
      .venv/Scripts/python.exe raw_call.py tia_describe '{"path": "screens"}'
"""


# Allow running this file directly from any working directory.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import subprocess
import sys
import threading

PYTHON = sys.executable
SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.py")


def project_path() -> str | None:
    """The project to connect to: TIA_PROJECT_PATH, else the last argument."""
    from_env = os.environ.get("TIA_PROJECT_PATH")
    if from_env:
        return from_env
    for candidate in sys.argv[2:]:
        if candidate.lower().endswith((".ap16", ".ap17", ".ap18", ".ap19", ".ap20", ".ap21")):
            return candidate
    return None


def main(argv: list[str]) -> int:
    tool = argv[1]
    arguments = json.loads(argv[2]) if len(argv) > 2 else {}

    process = subprocess.Popen(
        [PYTHON, SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    stderr: list[str] = []
    threading.Thread(
        target=lambda: [stderr.append(line.rstrip()) for line in process.stderr], daemon=True
    ).start()

    def send(payload):
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()

    def receive(wanted_id):
        while True:
            line = process.stdout.readline()
            if not line:
                raise RuntimeError("server closed stdout")
            line = line.strip()
            if not line:
                continue
            message = json.loads(line)
            if message.get("id") == wanted_id:
                return message

    try:
        send({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "raw", "version": "1"},
            },
        })
        receive(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        if tool != "tia_status":
            send({
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "tia_connect", "arguments": {"project_path": project_path()}},
            })
            print("connect:", json.dumps(receive(2), ensure_ascii=False)[:300])
        send({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        })
        print(f"\n=== raw response for {tool} ===")
        print(json.dumps(receive(3), indent=2, ensure_ascii=False))
        return 0
    finally:
        process.stdin.close()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        for line in stderr[:5]:
            print("stderr: " + line)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
