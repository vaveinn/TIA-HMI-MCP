"""MCP server for authoring WinCC Unified HMI screens through TIA Portal Openness.

Every tool marshals its Openness work onto one dedicated thread, because the
Openness API is not thread safe.

Run:  .venv/Scripts/python.exe server.py
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import tia_openness as tia

server = MCPServer(
    name="tia-hmi-mcp",
    instructions=(
        "Drive TIA Portal (WinCC Unified, TIA V21) through Openness.\n\n"
        "First contact with a project: ask these three, one at a time, in the "
        "user's own language, and wait for each answer before authoring "
        "anything.\n"
        "1. Target panel. tia_list_devices first. If an HMI is already there, "
        "confirm it. If not, do not choose one yourself - show the user the "
        "models from tia_list_panel_models with their screen sizes, let them "
        "pick, and only then create it with tia_add_hmi_device.\n"
        "2. Design source. Ask whether there is a design file - a Figma or "
        "即时设计 export as an image, or a share link. If there is one, design "
        "to it and skip question 3.\n"
        "3. Requirements, only when there is no design: which screens are "
        "needed, what each one does, and what it should look like.\n\n"
        "After building or changing a screen, call tia_check_layout and fix "
        "every entry in errors until the verdict is pass.\n\n"
        "Typical flow:\n"
        "1. tia_status to see running TIA Portal instances.\n"
        "2. tia_connect (with project_path when a project is not already open).\n"
        "3. tia_list_devices / tia_list_screens / tia_list_tags to orient.\n"
        "4. tia_create, tia_create_screen_item, tia_set_attributes to author.\n"
        "5. tia_compile, then tia_save_project.\n\n"
        "Paths address objects inside the HMI software:\n"
        "  screens/<screen>\n"
        "  screens/<screen>/items/<item>\n"
        "  tagtables/<table>\n"
        "  tagtables/<table>/tags/<tag>\n"
        "  connections/<connection>\n"
        "  screengroups/<group>, tagtablegroups/<group>\n"
        "Prefix with '<hmiDevice>/' when the project holds more than one HMI.\n"
        "Use tia_describe to discover the attribute names of any object, and "
        "tia_set_attributes to write them (colors accept '#RRGGBB' or [r,g,b]; "
        "object-valued attributes accept {\"$ref\": \"<path>\"})."
    ),
)


def _run(func, *args):
    """Execute Openness work on the dedicated thread.

    Failures come back as ToolError so the caller sees the reason; anything else
    is reported by the framework as a bare "Error executing tool", which is
    useless when the cause is a Siemens exception with a long stack.
    """
    try:
        return tia.run_on_openness_thread(func, *args)
    except Exception as exc:
        raise ToolError(f"{type(exc).__name__}: {tia._brief(exc, 600)}") from exc


# --------------------------------------------------------------------------
# Connection and session
# --------------------------------------------------------------------------


@server.tool()
def tia_status() -> dict[str, Any]:
    """List the TIA Portal versions installed and the instances currently running.

    Call this first. An empty instance list means no TIA Portal is open, so
    tia_connect will have to start one.
    """

    def work() -> dict[str, Any]:
        tia.bootstrap()
        instances = [
            {
                "id": p.id,
                "mode": p.mode,
                "version": p.version,
                "project_path": p.project_path,
            }
            for p in tia.list_portal_instances()
        ]
        session = tia.session()
        return {
            "api_version": tia.display_version(),
            "api_dir": tia.API_DIR,
            "instances": instances,
            "connected": session.connected,
            "project": str(session.project.Name) if session.project is not None else None,
        }

    return _run(work)


@server.tool()
def tia_connect(
    instance_id: int | None = None,
    mode: str = "without_ui",
    project_path: str | None = None,
) -> str:
    """Connect to TIA Portal and open a project.

    Attaches to a running instance when one matches; otherwise starts a new
    TIA Portal. A project must be opened before HMI objects can be reached.

    Args:
        instance_id: id from tia_status. Omit to take the only running instance,
            or to start a new one when none is running.
        mode: "without_ui" (default, headless, faster) or "with_ui". Only used
            when a new instance has to be started.
        project_path: full path to the .ap21 file. Omit when the target project
            is already open in the instance you attach to.
    """
    return _run(tia.session().connect, instance_id, mode, project_path)


@server.tool()
def tia_open_project(project_path: str) -> str:
    """Open another project in the connected TIA Portal instance.

    Args:
        project_path: full path to the .ap21 file.
    """
    return _run(tia.session().open_project, project_path)


@server.tool()
def tia_save_project() -> str:
    """Save the open project. Nothing is persisted in TIA Portal until this runs."""
    return _run(tia.session().save)


@server.tool()
def tia_disconnect(save: bool = False) -> str:
    """Close the project and release the TIA Portal connection.

    Args:
        save: save the project before closing.
    """
    return _run(tia.session().disconnect, save)


# --------------------------------------------------------------------------
# Browsing
# --------------------------------------------------------------------------


@server.tool()
def tia_list_devices() -> list[dict[str, Any]]:
    """List the devices in the project, marking the ones that are HMIs.

    HMI devices are the only ones this server can author; use their names as the
    optional prefix in object paths.
    """

    def work() -> list[dict[str, Any]]:
        session = tia.session()
        hmis = session.hmi_devices()
        return [
            {
                "name": str(device.Name),
                "type": str(device.TypeIdentifier),
                "is_hmi": str(device.Name) in hmis,
            }
            for device in session.devices()
        ]

    return _run(work)


@server.tool()
def tia_list_screens() -> list[dict[str, Any]]:
    """List every screen in the HMI, in creation order."""

    def work() -> list[dict[str, Any]]:
        hmi = tia.session().hmi_software()
        screens = []
        for screen in hmi.Screens:
            properties = tia.get_attributes(screen, ["ScreenNumber", "Width", "Height"])
            screens.append(
                {
                    "name": str(screen.Name),
                    "path": f"screens/{screen.Name}",
                    "number": properties.get("ScreenNumber"),
                    "width": properties.get("Width"),
                    "height": properties.get("Height"),
                }
            )
        return screens

    return _run(work)


@server.tool()
def tia_list_screen_items(screen_path: str) -> list[dict[str, Any]]:
    """List the controls and shapes placed on one screen.

    Args:
        screen_path: e.g. "screens/主画面".
    """

    def work() -> list[dict[str, Any]]:
        screen = tia.resolve(screen_path)
        items = []
        for item in screen.ScreenItems:
            geometry = tia.get_attributes(item, ["Left", "Top", "Width", "Height"])
            items.append(
                {
                    "name": str(item.Name),
                    "type": type(item).__name__,
                    "path": f"{screen_path}/items/{item.Name}",
                    **geometry,
                }
            )
        return items

    return _run(work)


@server.tool()
def tia_list_tags() -> list[dict[str, Any]]:
    """List the HMI tag tables and the tags in them."""

    def work() -> list[dict[str, Any]]:
        hmi = tia.session().hmi_software()
        tables = []
        for table in hmi.TagTables:
            tags = []
            for tag in table.Tags:
                tags.append(
                    {
                        "name": str(tag.Name),
                        "path": f"tagtables/{table.Name}/tags/{tag.Name}",
                        **tia.get_attributes(tag, ["HmiDataType", "Address"]),
                    }
                )
            tables.append({"name": str(table.Name), "tags": tags})
        return tables

    return _run(work)


@server.tool()
def tia_list_connections() -> list[dict[str, Any]]:
    """List the HMI's connections to controllers."""

    def work() -> list[dict[str, Any]]:
        hmi = tia.session().hmi_software()
        return [
            {
                "name": str(connection.Name),
                "path": f"connections/{connection.Name}",
                **tia.get_attributes(connection, ["CommunicationDriver", "InitialAddress"]),
            }
            for connection in hmi.Connections
        ]

    return _run(work)


# --------------------------------------------------------------------------
# Generic object access
# --------------------------------------------------------------------------


@server.tool()
def tia_describe(path: str, include_values: bool = False) -> dict[str, Any]:
    """Describe any object: its type, writable attributes, and child compositions.

    This is the discovery tool. Use it when you need an attribute name that is
    not covered by a dedicated tool - for example to find out what a widget
    exposes before calling tia_set_attributes.

    Args:
        path: object path, e.g. "screens/主画面/items/按钮1".
        include_values: also read the current value of every attribute.
    """

    def work() -> dict[str, Any]:
        obj = tia.resolve(path)
        attributes = []
        for info in tia.attribute_infos(obj):
            types = [str(t) for t in tia.declared_supported_types(info)]
            attributes.append(
                {"name": str(info.Name), "access": str(info.AccessMode), "types": types}
            )
        compositions = []
        try:
            compositions = [str(info.Name) for info in obj.GetCompositionInfos()]
        except Exception:
            pass
        result: dict[str, Any] = {
            "path": path,
            "type": type(obj).__name__,
            "attributes": attributes,
            "compositions": compositions,
        }
        if include_values:
            result["values"] = tia.get_attributes(obj, [a["name"] for a in attributes])
        return result

    return _run(work)


@server.tool()
def tia_get_attributes(path: str, names: list[str]) -> dict[str, Any]:
    """Read specific attributes of an object.

    Args:
        path: object path.
        names: attribute names, as reported by tia_describe.
    """
    return _run(lambda: tia.get_attributes(tia.resolve(path), names))


@server.tool()
def tia_set_attributes(path: str, attributes: dict[str, Any]) -> dict[str, str]:
    """Write attributes on any object. Reports per-attribute success or failure.

    Values are converted to the CLR type the attribute expects: colors accept
    "#RRGGBB", "255,0,0" or [r, g, b]; enum attributes accept the member name as
    a string; object-valued attributes (a tag's Connection, a dynamization's
    Tag) accept {"$ref": "<path>"}.

    Args:
        path: object path.
        attributes: attribute name -> value.
    """
    return _run(lambda: tia.set_attributes(tia.resolve(path), attributes))


@server.tool()
def tia_delete(path: str) -> str:
    """Delete any object: a screen, a screen item, a tag, a table, a connection.

    Args:
        path: object path. Compositions themselves cannot be deleted.
    """
    obj = _run(tia.resolve, path)
    _run(obj.Delete)
    return f"deleted {path}"


@server.tool()
def tia_create(parent_path: str, name: str) -> dict[str, Any]:
    """Create an object inside a composition.

    Args:
        parent_path: a composition path, e.g. "screens", "tagtables",
            "connections", "screengroups/组1/screens",
            "tagtables/表1/tags". Run tia_describe on a parent object and look
            at its compositions to find valid composition paths.
        name: name of the new object.
    """
    composition = _run(tia.resolve, parent_path)
    created = _run(composition.Create, name)
    return {"created": str(created.Name), "type": type(created).__name__}


@server.tool()
def tia_screen_item_types() -> list[str]:
    """List the control and shape types tia_create_screen_item accepts."""
    return _run(lambda: sorted(tia.screen_item_types()))


# --------------------------------------------------------------------------
# HMI authoring
# --------------------------------------------------------------------------


@server.tool()
def tia_create_screen_item(
    screen_path: str,
    item_type: str,
    name: str,
    left: int | None = None,
    top: int | None = None,
    width: int | None = None,
    height: int | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Place a control or shape on a screen.

    Args:
        screen_path: e.g. "screens/主画面".
        item_type: a type from tia_screen_item_types, e.g. "HmiButton",
            "HmiIOField", "HmiLabel", "HmiRectangle".
        name: name of the new item.
        left: x position in pixels.
        top: y position in pixels.
        width: width in pixels.
        height: height in pixels.
        attributes: further attributes, passed to tia_set_attributes. For a
            button that is usually {"Text": "启动"}.
    """
    item = _run(tia.create_screen_item, screen_path, item_type, name)

    geometry = {
        key: value
        for key, value in (
            ("Left", left),
            ("Top", top),
            ("Width", width),
            ("Height", height),
        )
        if value is not None
    }
    results = _run(tia.set_attributes, item, geometry) if geometry else {}
    if attributes:
        results.update(_run(tia.set_attributes, item, attributes))

    failures = {k: v for k, v in results.items() if v != "ok"}
    return {
        "path": f"{screen_path}/items/{name}",
        "type": item_type,
        "attribute_results": results,
        "failures": failures,
    }


@server.tool()
def tia_bind_tag(item_path: str, property_name: str, tag_path: str) -> str:
    """Bind an HMI tag to a property of a screen item.

    The property is driven by a tag dynamization, because properties such as an
    IO field's ProcessValue are declared as String and cannot take a tag object
    directly.

    Args:
        item_path: e.g. "screens/主画面/items/温度显示".
        property_name: the property to drive, e.g. "ProcessValue" for an
            HmiIOField or "Text" for an HmiButton. Use tia_describe on the item
            to find the exact name.
        tag_path: e.g. "tagtables/默认变量表/tags/温度".
    """
    return _run(tia.bind_tag, item_path, property_name, tag_path)


@server.tool()
def tia_compile(hmi_device: str | None = None) -> dict[str, Any]:
    """Compile the HMI software and report errors and warnings.

    Args:
        hmi_device: HMI device name. Only needed when the project has several.
    """
    return _run(tia.compile_hmi_software, hmi_device)


# --------------------------------------------------------------------------
# Panels
# --------------------------------------------------------------------------


@server.tool()
def tia_list_panel_models() -> list[dict[str, Any]]:
    """List the WinCC Unified panel models this installation can create.

    Polled from the hardware catalog, so it matches what is actually installed.
    Use this when the project has no HMI yet: show the models with their screen
    sizes, let the user pick one, then pass its type_identifier to
    tia_add_hmi_device. Needs a connection but no project.
    """
    return _run(tia.list_panel_models)


@server.tool()
def tia_add_hmi_device(type_identifier: str, name: str) -> dict[str, Any]:
    """Create an HMI panel in the open project, from a catalog type identifier.

    This writes to the project, so confirm the model with the user first. The
    panel arrives without any screen; create those with tia_create("screens",
    ...). Nothing reaches disk until tia_save_project runs.

    Args:
        type_identifier: from tia_list_panel_models, e.g.
            "OrderNumber:6AV2 123-3GB32-0AW0/21.0.0.0" for a 7" MTP700
            Unified Basic.
        name: device name, e.g. "HMI_1". Must not already exist in the project.
    """
    return _run(tia.add_hmi_device, type_identifier, name)


# --------------------------------------------------------------------------
# Layout diagnostics
# --------------------------------------------------------------------------


def _image_path(screen_name: str) -> str:
    """A temp PNG path for a screen, with filename-hostile characters flattened."""
    safe = "".join(character if character.isalnum() else "_" for character in screen_name)
    return os.path.join(tempfile.gettempdir(), f"tia_layout_{safe}.png")


@server.tool()
def tia_check_layout(screen_path: str | None = None, render: bool = True) -> dict[str, Any]:
    """Check screens for geometric, contrast and legibility problems.

    Reads the screens back out of TIA Portal and runs the layout checker over
    them. A "fail" verdict means errors that have to be fixed before the screen
    is usable: work through `errors`, then call this again until the verdict is
    "pass". Warnings never block. With `render`, each screen is also redrawn to
    a PNG in the temp folder - Openness cannot screenshot a screen, so this is
    the only way to actually look at the layout.

    Args:
        screen_path: one screen, e.g. "screens/主画面". Omit to check them all.
        render: also measure the real text widths and write a PNG per screen.
    """

    def work() -> dict[str, Any]:
        import layout as layout_checks  # noqa: PLC0415
        import render as renderer  # noqa: PLC0415

        layouts = tia.read_layouts([screen_path] if screen_path else None)

        widths: dict[str, dict[str, float]] = {}
        images: dict[str, str] = {}
        render_error = None
        if render:
            try:
                font_path = renderer.find_font_path()
                for one in layouts:
                    widths[one["screen"]] = renderer.measure_text_widths(one["items"], font_path)
                    images[one["screen"]] = renderer.save_layout(
                        one["items"],
                        one["panel"],
                        _image_path(one["screen"]),
                        font_path=font_path,
                        background=one["screen_bg"],
                    )["path"]
            except Exception as exc:
                render_error = f"{type(exc).__name__}: {tia._brief(exc, 200)}"
                widths, images = {}, {}

        report = layout_checks.check_all(
            [
                {
                    "name": one["screen"],
                    "panel": one["panel"],
                    "items": one["items"],
                    "screen_bg": one["screen_bg"],
                }
                for one in layouts
            ],
            text_widths=widths,
        )
        for result, one in zip(report["screens"], layouts):
            result["hidden_items"] = one["hidden_items"]
        report["images"] = images
        if render_error:
            report["render_error"] = render_error
        return report

    return _run(work)


@server.tool()
def tia_export_tags(directory: str, tag_table: str | None = None) -> str:
    """Export HMI tags to XLSX files in a directory.

    Only tags, scripts and text/graphic lists are exportable. TIA Portal
    Openness has no import or export API at all for WinCC Unified screens.

    Args:
        directory: target directory, created if missing.
        tag_table: export one table only. Omit to export every table.
    """
    return _run(tia.export_tags, directory, tag_table)


def main() -> None:
    """Console entry point."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
