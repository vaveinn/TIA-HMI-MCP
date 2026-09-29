# Tool reference

23 tools, all prefixed `tia_`. Object paths are described in
[Object paths](#object-paths) at the end.

## Session

| Tool | Arguments | Returns |
|---|---|---|
| `tia_status` | – | API version, API folder, every running TIA instance (id, mode, installed products, project path), and whether a session is connected. **Call this first.** |
| `tia_connect` | `instance_id?` `mode?` `project_path?` | Connects. Attaches to a running instance when one matches, otherwise starts a new TIA Portal. `mode`: `"without_ui"` (default) or `"with_ui"`, used only when starting a new instance. `project_path` accepts the `.ap*` file or the project folder; a project already open in TIA is adopted, never re-opened. |
| `tia_open_project` | `project_path` | Switches to another project in the connected instance. |
| `tia_save_project` | – | `Project.Save()`. Nothing reaches disk until this runs. |
| `tia_disconnect` | `save?` | Releases the Openness session. A project that was already open in TIA stays open; a project this session opened itself is closed. |

## Browsing

| Tool | Arguments | Returns |
|---|---|---|
| `tia_list_devices` | – | Every device with `is_hmi` flagging the Unified HMI targets. |
| `tia_list_screens` | – | Screens with name, path, number, width, height. |
| `tia_list_screen_items` | `screen_path` | Items on one screen: name, CLR type, path, and geometry. |
| `tia_list_tags` | – | Tag tables and their tags, with `HmiDataType` and `Address`. |
| `tia_list_connections` | – | HMI connections with communication driver and initial address. |

## Generic object access

These reach anything the specialised tools do not cover.

| Tool | Arguments | Returns |
|---|---|---|
| `tia_describe` | `path` `include_values?` | Object type, every attribute (name, access mode, supported CLR types), and child composition names. This is the discovery tool — use it to find an attribute name before writing it. |
| `tia_get_attributes` | `path` `names` | Values of the named attributes. |
| `tia_set_attributes` | `path` `attributes` | Per-name `"ok"` or `"failed: …"`. See [value forms](#value-forms) below. |
| `tia_delete` | `path` | Deletes a screen, item, tag, table or connection. Compositions cannot be deleted. |
| `tia_create` | `parent_path` `name` | Creates inside a composition. `parent_path` is a composition path, e.g. `screens`, `tagtables`, `connections`, `screengroups/组1/screens`, `tagtables/表1/tags`. |

## HMI authoring

| Tool | Arguments | Returns |
|---|---|---|
| `tia_screen_item_types` | – | Control and shape type names `tia_create_screen_item` accepts on this installation. |
| `tia_create_screen_item` | `screen_path` `item_type` `name` `left?` `top?` `width?` `height?` `attributes?` | Creates a control and applies geometry plus any further attributes; reports per-attribute failures. |
| `tia_bind_tag` | `item_path` `property_name` `tag_path` | Binds a tag to a property through a tag dynamization. `property_name` must be a real dynamizable property of the item — `ProcessValue` for an IO field, `Text` for a button. |

## Panels

| Tool | Arguments | Returns |
|---|---|---|
| `tia_list_panel_models` | – | Every WinCC Unified panel the installed hardware catalog offers: article number, `type_identifier`, name, catalog path. Polled from the catalog, so it matches the installation. Needs a connection but no project. Show this to the user when the project has no HMI yet and let them pick. |
| `tia_add_hmi_device` | `type_identifier` `name` | Creates a panel in the open project. `type_identifier` comes from `tia_list_panel_models`. The panel arrives with no screens. Writes to the project, so confirm the model first; nothing reaches disk until `tia_save_project`. |

## Layout

| Tool | Arguments | Returns |
|---|---|---|
| `tia_check_layout` | `screen_path?` `render?` | Reads the screens back out of TIA Portal and checks geometry, overlap, touch sizes, colour contrast, fonts, bindings and real text width. Returns a `verdict` (`"pass"` / `"fail"`), `errors` and `warnings`, every entry carrying a `fix`, and a `next_action`. One screen, or all of them when `screen_path` is omitted. With `render` (the default) each screen is also redrawn to a PNG in the temp folder, because Openness cannot screenshot a screen; `images` carries the paths. |

`verdict: "fail"` means errors that have to be fixed - work through `errors` and
call the tool again until it reads `"pass"`. Warnings never block. The checks
run offline over `layout.py`, so they also have their own test suite:

```bash
.venv\Scripts\python.exe tests\test_layout.py
.venv\Scripts\python.exe tests\test_bridge.py
```

## Build and export

| Tool | Arguments | Returns |
|---|---|---|
| `tia_compile` | `hmi_device?` | Compiles the HMI software and flattens the message tree into readable text, with error and warning counts. `hmi_device` is only needed when the project has several HMIs. |
| `tia_export_tags` | `directory` `tag_table?` | Exports tags to XLSX. |

## Value forms

`tia_set_attributes` and the `attributes` argument of `tia_create_screen_item`
accept these JSON values:

| Target type | Write it as |
|---|---|
| number, string, bool | the literal, e.g. `40`, `"启动"`, `true` |
| text property (`Text`) | a plain string — the `MultilingualText` wrapper is unwrapped automatically |
| colour | `"#1E88E5"`, `"30,136,229"` or `[30, 136, 229]` |
| enum | the member name as a string, e.g. `"CyclicContinuous"` |
| object reference (a tag's `Connection`, a screen's template) | `{"$ref": "<path>"}` |

## Object paths

Paths are rooted at the HMI software. Areas:

```
screens/<screen>                      screens/<screen>/items/<item>
tagtables/<table>                     tagtables/<table>/tags/<tag>
connections/<connection>
screengroups/<group>                  tagtablegroups/<group>
textlists/<list>                      graphiclists/<list>
```

A composition is itself a valid path and is what `tia_create` wants as
`parent_path`:

```
screens                        create a screen here
screengroups/组1/screens        create a screen inside a group
tagtables/表1/tags              create a tag here
```

When a project holds more than one HMI, prefix the path with the device name:
`HMI_1/screens/主画面`.
