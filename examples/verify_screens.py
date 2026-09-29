"""Verify the built screens through the MCP tool functions and compile.

Run:  .venv/Scripts/python.exe verify_screens.py
"""


# Allow running this file directly from any working directory.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import tia_openness as tia

PROJECT_PATH = os.environ.get("TIA_PROJECT_PATH") or (sys.argv[1] if len(sys.argv) > 1 else "")


def main() -> int:
    import server

    tia.bootstrap()
    session = tia.session()
    print(tia.run_on_openness_thread(session.connect, None, "without_ui", PROJECT_PATH))

    print("\n### tia_list_screens")
    screens = server.tia_list_screens()
    print(json.dumps(screens, indent=2, ensure_ascii=False, default=str))

    for screen in screens:
        path = screen["path"]
        print(f"\n### tia_list_screen_items({path})")
        items = server.tia_list_screen_items(path)
        print(json.dumps(items, indent=2, ensure_ascii=False, default=str))

    print("\n### 变量绑定检查")
    def check_bindings():
        hmi = session.hmi_software()
        out = []
        for screen in hmi.Screens:
            for item in screen.ScreenItems:
                for dyn in item.Dynamizations:
                    out.append({
                        "画面": str(screen.Name),
                        "控件": str(item.Name),
                        "属性": str(dyn.PropertyName),
                        "变量": str(dyn.Tag),
                    })
        return out

    bindings = tia.run_on_openness_thread(check_bindings)
    print(json.dumps(bindings, indent=2, ensure_ascii=False, default=str))
    print(f"共 {len(bindings)} 条绑定")

    print("\n### 变量表")
    print(json.dumps(server.tia_list_tags(), indent=2, ensure_ascii=False, default=str))

    print("\n### tia_compile")
    try:
        result = server.tia_compile()
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    except Exception as exc:
        print(f"编译失败: {type(exc).__name__}: {str(exc)[:400]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
