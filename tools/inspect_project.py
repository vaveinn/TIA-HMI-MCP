"""Read-only inspection of the project currently open in TIA Portal.

Attaches to the running instance and reports the device make-up, the HMI
screens and their items, and how attributes behave on a real object.

Run:  .venv/Scripts/python.exe inspect_project.py
"""


# Allow running this file directly from any working directory.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import tia_openness as tia

PROJECT_PATH = os.environ.get("TIA_PROJECT_PATH") or (sys.argv[1] if len(sys.argv) > 1 else "")


def show(label: str, value) -> None:
    print(f"\n### {label}\n{json.dumps(value, indent=2, ensure_ascii=False, default=str)}")


def guess(label: str, func, *args):
    try:
        return func(*args)
    except Exception as exc:
        print(f"\n!! {label} raised {type(exc).__name__}: {str(exc)[:400]}")
        return None


def main() -> int:
    tia.bootstrap()
    session = tia.session()

    print("instances:", [(p.id, p.mode, p.project_path) for p in tia.list_portal_instances()])
    print("\n--- attaching ---")
    print(tia.run_on_openness_thread(session.connect, None, "without_ui", PROJECT_PATH))

    devices = guess("list devices", lambda: [
        {"name": str(d.Name), "type": str(d.TypeIdentifier)} for d in session.devices()
    ])
    show("devices", devices)

    hmis = guess("hmi_devices", session.hmi_devices)
    if not hmis:
        print(
            "\n>>> No WinCC Unified HMI found. If your panel is a classic Comfort/Advanced "
            "panel, this server cannot author it."
        )
        return 1
    show("hmi devices found", list(hmis))

    hmi = next(iter(hmis.values()))

    screens = guess("screens", lambda: [str(s.Name) for s in hmi.Screens])
    show("screens", screens)

    tables = guess("tagtables", lambda: [
        {"table": str(t.Name), "tags": [str(g.Name) for g in t.Tags]} for t in hmi.TagTables
    ])
    show("tag tables", tables)

    connections = guess("connections", lambda: [
        {
            "name": str(c.Name),
            "driver": str(c.CommunicationDriver),
            "attributes": _attribute_names(c),
        }
        for c in hmi.Connections
    ])
    show("connections", connections)

    if screens:
        screen = hmi.Screens.Find(screens[0])
        items = guess("screen items", lambda: [
            {
                "name": str(i.Name),
                "type": type(i).__name__,
                "attributes": _attribute_names(i),
                "Left": _read(i, "Left"),
                "Text": _read(i, "Text"),
            }
            for i in screen.ScreenItems
        ])
        show(f"items on '{screens[0]}'", items)

    print("\n--- done (nothing modified) ---")
    return 0


def _attribute_names(obj) -> list:
    try:
        return [str(info.Name) for info in obj.GetAttributeInfos]
    except Exception as exc:
        return [f"<GetAttributeInfos failed: {type(exc).__name__}: {str(exc)[:200]}>"]


def _read(obj, name):
    try:
        return str(obj.GetAttribute(name))
    except Exception as exc:
        return f"<{type(exc).__name__}: {str(exc)[:120]}>"


if __name__ == "__main__":
    raise SystemExit(main())
