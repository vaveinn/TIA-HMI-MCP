"""List the WinCC Unified panels this MCP can drive, by polling the catalog.

Attaches to a running TIA Portal instance when one is available and asks the
hardware catalog for every MTP/Unified panel, so the supported-model list can be
read off a real installation instead of a doc that may be out of date.

Run:  .venv/Scripts/python.exe list_panels.py
"""


# Allow running this file directly from any working directory.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tia_openness as tia

# Partial identifiers the catalog accepts; MTP is the Unified panel prefix.
FAMILIES = ["MTP400", "MTP700", "MTP1000", "MTP1200", "MTP1500", "MTP1900", "MTP2200"]


def main() -> int:
    tia.bootstrap()
    session = tia.session()
    print(tia.run_on_openness_thread(session.connect, None, "without_ui", None))

    def work():
        catalog = session.portal.HardwareCatalog
        seen: dict[str, dict] = {}
        for family in FAMILIES:
            try:
                entries = list(catalog.Find(family))
            except Exception as exc:
                print(f"Find({family!r}) failed: {type(exc).__name__}: {str(exc)[:120]}")
                continue
            for entry in entries:
                article = _attr(entry, "ArticleNumber")
                path = _attr(entry, "CatalogPath")
                if article:
                    seen[article] = {"path": path, "type": _attr(entry, "TypeIdentifier")}

        print(f"\n{'订货号 / Article number':28}  catalog path")
        print("-" * 100)
        for article in sorted(seen):
            print(f"{article:28}  {seen[article]['path']}")
        print(f"\ntotal: {len(seen)} panel variants")

    tia.run_on_openness_thread(work)
    return 0


def _attr(entry, name) -> str:
    try:
        return str(entry.GetAttribute(name))
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
