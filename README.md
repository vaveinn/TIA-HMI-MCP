# TIA-HMI-MCP

An MCP server that drives **Siemens TIA Portal** through the **Openness** API to
build **WinCC Unified** HMI screens. Point an MCP client at it and the agent
authors the panel for you.

What it can do:

* **create a panel** from the hardware catalog installed on the machine, so the
  model list always matches that TIA version;
* **create screens** and place buttons, IO fields, labels, shapes and the rest
  of the Unified control set, at exact geometry and colours;
* **create HMI tags** and bind a tag to any control property;
* **check a screen** for out-of-bounds and overlapping controls, touch targets
  that are too small, contrast, font size, and captions that do not fit — every
  finding carries a concrete fix;
* **redraw each screen to a PNG**, because Openness cannot screenshot one, so a
  vision-capable agent can judge the layout itself;
* **compile** the HMI software and report errors and warnings.

Verified end to end against a TIA Portal V21 project on a 7" MTP700 Unified Basic
panel: four screens, 105 objects, 11 tags, 11 tag bindings, clean compile.

## Documentation

| Document | Contents |
|---|---|
| **[docs/PANELS.md](docs/PANELS.md)** | **Which touch panels work** — full model and article-number lists, what is unsupported and why, control subset per panel |
| [docs/TOOLS.md](docs/TOOLS.md) | Every tool: arguments, return values, object-path syntax, accepted value forms |
| [docs/API-NOTES.md](docs/API-NOTES.md) | Openness API landmines found by experiment, including the two calls that crash TIA Portal |
| [docs/SHARING.md](docs/SHARING.md) | Handing this server to someone else: prerequisites on their machine, what not to ship, how to register it |

## Requirements

| | |
|---|---|
| TIA Portal | **V21** with the WinCC Unified option (V16+ may work with `TIA_OPENNESS_API_DIR`, untested) |
| HMI target | Any **WinCC Unified** panel — see [docs/PANELS.md](docs/PANELS.md). Classic Comfort/Advanced/Basic panels are **not** supported, by vendor API limitation |
| Python | 3.11 – 3.14 (3.14.7 verified) |
| Windows group | The current user must be in the **`Siemens TIA Openness`** Windows group |
| .NET | .NET Framework 4.8 (ships with Windows) |

## Install

```bash
cd <the folder you cloned this into>
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Verify the environment without touching a project:

```bash
.venv\Scripts\python.exe tests\smoke_test.py         # do the tools register and reach Openness? (no project needed)
.venv\Scripts\python.exe tests\test_mcp_protocol.py  # does the server answer real MCP over stdio?
```

`test_mcp_protocol.py` drives a live TIA Portal and finishes with
`tia_disconnect(save: false)`, so it **closes whatever project is open and
discards its unsaved changes**. Do not run it while you have unsaved work.

## Register with Claude Code

```bash
claude mcp add tia-hmi-mcp -s user -- "<repo>\.venv\Scripts\python.exe" "<repo>\server.py"
```

with `<repo>` the clone folder. This writes to `%USERPROFILE%\.claude.json` under `mcpServers`. Check it with
`claude mcp list`, remove it with `claude mcp remove tia-hmi-mcp -s user`.

MCP servers load at session start, so restart Claude Code after registering.

## Guided setup

The server does not interrogate you through elicitation - it hands the agent a
flow, and the agent asks you. On first contact with a project, three questions,
one at a time:

1. **Target panel.** If the project already holds a Unified panel, it is
   confirmed and you go straight on. If it holds none, the agent does not pick
   one: it lists the models `tia_list_panel_models` reads off your installed
   catalog, with their screen sizes, and waits for you to choose. Then
   `tia_add_hmi_device` creates it.
2. **Design source.** If you have a design file - a Figma or 即时设计 export as
   an image, or a share link - the screens are built to it, and question 3 is
   skipped.
3. **Requirements.** Only when there is no design: which screens you need, what
   each one does, and what it should look like.

Every screen is then checked with `tia_check_layout` and fixed until it passes.

## Quick start

```
tia_status()                                    # what TIA instances are running?
tia_connect(project_path=r"E:\...\demo.ap21")   # attach and adopt the open project
tia_list_devices()                              # confirm an HMI is present
tia_describe("screens")                         # what can be created here?

tia_create("screens", "主画面")
tia_create("tagtables", "AI演示变量")
tia_create("tagtables/AI演示变量/tags/温度")

tia_create_screen_item("screens/主画面", "HmiButton", "启动按钮",
                       left=40, top=60, width=160, height=48,
                       attributes={"Text": "启动", "BackColor": "#1E88E5"})

tia_create_screen_item("screens/主画面", "HmiIOField", "温度显示",
                       left=40, top=140, width=200, height=40)
tia_bind_tag("screens/主画面/items/温度显示", "ProcessValue",
             "tagtables/AI演示变量/tags/温度")

tia_check_layout()                              # geometry, contrast, and a PNG
tia_compile()                                   # verify
tia_save_project()                              # persist
```

## Layout checks

Openness cannot screenshot a screen, so `tia_check_layout` reads the geometry,
colours, fonts, captions and tag bindings back out of TIA Portal and then:

* **checks** them offline - out-of-bounds, partially overlapping or exactly
  coincident controls, touch targets under 40 px, unbound IO fields, contrast
  under 3.0, fonts under 12 pt, captions wider than the control they sit in,
  duplicate names. Every error carries a `fix`;
* **renders** each screen to a PNG in the temp folder, so the layout can be
  looked at for the things no rule catches - a control sitting on top of a
  title, a crowd that is technically legal.

The verdict is the gate: `"fail"` means fix every entry in `errors` and call it
again; `"pass"` means the screen is usable, with warnings left as advice.

## Repository layout

```
tia-hmi-mcp/
├── server.py           MCP server, 23 tools over stdio
├── tia_openness.py     the bridge: assembly bootstrap, session, path resolution,
│                       attribute access, panels, layout reading, build and
│                       compile helpers
├── layout.py           the layout checker: pure functions over plain data,
│                       no Openness, no Pillow
├── render.py           redraws a screen to a PNG, so a layout can be looked at
├── pyproject.toml      packaging; console script `tia-hmi-mcp`
├── docs/
│   ├── PANELS.md       which touch panels work
│   ├── TOOLS.md        tool reference
│   ├── API-NOTES.md    Openness API landmines
│   └── SHARING.md      handing the server to someone else
├── examples/           runnable worked examples
│   ├── build_screens.py    builds four screens from data tables
│   └── verify_screens.py   lists screens, items and bindings, then compiles
├── tools/              diagnostics
│   ├── list_panels.py      enumerate installed Unified panel models
│   ├── inspect_project.py  read-only survey of the open project
│   └── raw_call.py         call one tool, print the raw JSON-RPC response
└── tests/
    ├── smoke_test.py         tool registration and a live tia_status call
    ├── test_mcp_protocol.py  real MCP over stdio: handshake, tools/list, tools/call
    ├── test_bridge.py        the two silent write defects, CLR faked out
    ├── test_layout.py        every checker rule, both directions
    └── test_render.py        the renderer, including CJK text
```

Every script takes the project path either from the `TIA_PROJECT_PATH`
environment variable or from its first argument, so nothing is tied to one
machine:

```bash
set TIA_PROJECT_PATH=E:\path\to\project.ap21
.venv\Scripts\python.exe examples\build_screens.py
```

`examples\build_screens.py` is idempotent — it deletes same-named screens and
rebuilds them — and does not save the project, so it is safe to re-run while
tuning a layout.

## Configuration

| Environment variable | Purpose |
|---|---|
| `TIA_OPENNESS_API_DIR` | Folder holding the Openness assemblies, e.g. `<TIA install>\Portal V21\PublicAPI\V21\net48`. Only needed to override discovery — by default the folder is located automatically from the TIA installations registered with Windows. |
| `TIA_OPENNESS_EXTRA_DIRS` | Extra assembly search folders, separated by `;`. Needed when moving to another TIA version. |

## Behaviour worth knowing

* **Attaching is preferred over starting.** TIA holds a project open exclusively,
  so a second instance cannot open a project the first one has. `tia_connect`
  attaches to a running instance and adopts the project already open in it.
* **Projects are never closed behind your back.** `tia_disconnect` only releases
  the Openness session and leaves a project that TIA has open exactly where it
  was; projects this session opened itself are closed.
* **Nothing is written to disk until `tia_save_project`.** Changes live in TIA's
  memory, so closing TIA without saving discards them.
* **All Openness calls run on one thread.** Openness is not thread safe, and MCP
  tool calls would otherwise land on arbitrary thread pool threads.
* **The server never calls `IEngineeringObject.SetAttribute`.** On Unified objects
  it raises `NonRecoverableException` and crashes TIA Portal. See
  [docs/API-NOTES.md](docs/API-NOTES.md).

## Troubleshooting

| Symptom | Cause |
|---|---|
| `The user does not have the necessary permissions` | The Windows user is not in the `Siemens TIA Openness` group. Sign out and back in. |
| `FileNotFoundException: Siemens.Engineering.Contract` | The assembly lives in `<TIA install>\Bin\PublicAPI`, which this server adds automatically. For an unusual layout, set `TIA_OPENNESS_EXTRA_DIRS`. |
| `No WinCC Unified HMI found in this project` | The project has no Unified panel, or the panel is a classic one. See [docs/PANELS.md](docs/PANELS.md). |
| `Unable to open the project under path …` | The project is already open in TIA. Let `tia_connect` adopt it by passing the same path, or omit `project_path` entirely. |
| A tool returns `isError` with a pythonnet type error | Almost always a wrong type in a property write. Run `tia_describe` on the object first and check [docs/API-NOTES.md](docs/API-NOTES.md). |
