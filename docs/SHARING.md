# Sharing this server with someone else

This is not a self-contained tool. It is a thin bridge to a **locally installed**
TIA Portal, so the code is the easy half of the handover: without TIA on the
other machine it installs cleanly and then never connects to anything.

Send the code, but tell the recipient the prerequisites first, or you will get
bug reports that are really missing installs.

## Prerequisites on the recipient's machine

| | Requirement | Why it bites |
|---|---|---|
| TIA Portal | **V21** with the WinCC Unified option | The code targets V21's `HmiUnified` object model. `PublicAPI\V*` is discovered automatically, so a V18/V19 install may load and then fail on a specific call. Ask before sending. |
| Windows group | The current user must be in the local group **`Siemens TIA Openness`** | Without it `TiaPortal.GetProcesses()` throws. Easiest step to miss; it is set in `lusrmgr.msc` → Local Users and Groups → Groups. |
| License | A TIA Portal license that covers the panel | Openness is not a licence bypass. |
| .NET | .NET Framework 4.8 | Ships with Windows. pythonnet runs on the netfx runtime here. |
| Python | 3.11 – 3.14 | |
| Panel | Any **WinCC Unified** panel | Classic Comfort / Advanced / Basic panels cannot be authored through Openness at all — see [PANELS.md](PANELS.md). |

If `TIA_OPENNESS_API_DIR` is set on your machine, it will not be set on theirs;
leave it unset so the automatic search runs.

## What not to ship

| Do not send | |
|---|---|
| `.venv/` | Holds absolute paths and this machine's interpreter. Rebuild it on the far side. |
| Siemens Openness DLLs | Licensed by Siemens. Never bundle them; the code finds the local installation itself. |
| `.ap21` / `.ap*-backup` projects | Someone else's project data. |
| Absolute personal paths | Replaced by placeholders in this repo's docs — keep it that way. |

## Ways to send it

| Route | Use when |
|---|---|
| **Clone the repository** (`pip install -e .`) | Default choice. TIA's API surface drifts between versions, so source beats a frozen artefact. |
| **Zip the source** | One-off handover. Exclude `.venv/` and `__pycache__/`, then `pip install -r requirements.txt`. |
| **Wheel** (`python -m build`) | Pinned, tested environments. Note the modules install flat into site-packages, so a collision with another `layout` or `render` package would silently shadow this one. |
| **`.mcpb` bundle** | A recipient who does not want a terminal. Needs a manifest, and the Python dependencies still have to be resolved somewhere. |

## Registering it over there

Claude Code:

```bash
claude mcp add tia-hmi-mcp -s user -- "<repo>\.venv\Scripts\python.exe" "<repo>\server.py"
```

Claude Desktop, in `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tia-hmi-mcp": {
      "command": "<repo>\\.venv\\Scripts\\python.exe",
      "args": ["<repo>\\server.py"]
    }
  }
}
```

MCP servers are read at startup, so restart the client afterwards.

## First thing to run over there

```bash
.venv\Scripts\python.exe tests\smoke_test.py
```

It registers the tools and reaches Openness without opening a project, so it
separates "the install is broken" from "the project is odd". If it passes and
`tia_list_devices` still returns nothing, the problem is on the TIA side.

## Also read

[docs/API-NOTES.md](API-NOTES.md) is the part worth hand-delivering: it records
two Openness calls that **crash TIA Portal** and can lose unsaved work. Pass it
along with the code, and say so out loud.
