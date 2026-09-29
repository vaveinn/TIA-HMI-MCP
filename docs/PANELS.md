# Supported HMI panels

This MCP drives **WinCC Unified** targets only. It works with a panel when the
panel's software resolves to `Siemens.Engineering.HmiUnified.HmiSoftware`.

The lists below were read from a live TIA Portal V21 hardware catalog with
[`list_panels.py`](../tools/list_panels.py); re-run that script on any installation to
regenerate them.

A panel can also be **created** by the server, so a project that has none yet
needs no trip through the TIA UI: `tia_list_panel_models` reports what the
installed catalog offers, and `tia_add_hmi_device` creates the chosen one from
its `type_identifier` (`OrderNumber:<article>/<version>`; the version suffix is
not fussy - the catalog returns `.../18.0.0.3` for the 7" Basic while
`.../21.0.0.0` creates the same panel). Verified with a 7" MTP700 Unified
Basic, `6AV2 123-3GB32-0AW0`, which comes up as an 800x480 screen with no
screens defined.

## Supported — SIMATIC Unified Basic Panel

| Size | Panel | Article number |
|---|---|---|
| 4" | MTP400 Unified Basic | `6AV2 123-3DB32-0AW0` |
| 7" | MTP700 Unified Basic | `6AV2 123-3GB32-0AW0` |
| 10" | MTP1000 Unified Basic | `6AV2 123-3KB32-0AW0` |
| 12" | MTP1200 Unified Basic | `6AV2 123-3MB32-0AW0` |

## Supported — SIMATIC Unified Comfort Panel

| Size | Panel | Article number |
|---|---|---|
| 7" | MTP700 Unified Comfort | `6AV2 128-3GB06-0AXx` |
| 10" | MTP1000 Unified Comfort | `6AV2 128-3KB06-0AXx` |
| 12" | MTP1200 Unified Comfort | `6AV2 128-3MB06-0AXx` |
| 15" | MTP1500 Unified Comfort | `6AV2 128-3QB06-0AXx` |
| 19" | MTP1900 Unified Comfort | `6AV2 128-3UB06-0AXx` |
| 22" | MTP2200 Unified Comfort | `6AV2 128-3XB06-0AXx` |

## Supported — Unified Comfort PRO and SIPLUS

| Panel | Article number |
|---|---|
| MTP1200 Unified Comfort PRO | `6AV2 128-3MB27-*` |
| MTP1500 Unified Comfort PRO | `6AV2 128-3QB27-*` |
| MTP1900 Unified Comfort PRO | `6AV2 128-3UB27-*` |
| MTP2200 Unified Comfort PRO | `6AV2 128-3XB27-*` |
| MTP400/700/1000/1200 Unified Basic SIPLUS | `6AG1 123-3*32-2AW0` |
| MTP700/1000/1200/1500 Unified Comfort SIPLUS | `6AG1 128-3*06-4AXx` |

A SIMATIC **Unified PC station** (WinCC Unified PC runtime) is the same software
target and should work as well, but it has not been tested here.

## Not supported — classic WinCC panels

Every classic panel is out: **Comfort**, **Advanced** and **Basic** alike —
KTP400, KTP700 Basic, KTP700/TP700 Comfort, TP900, TP1200 Comfort, TP1500,
TP1900, TP2200 Comfort, OP/MP series, and WinCC Runtime PC / WinCC Professional.

This is a limit of the vendor API, not a gap in this server:

* the symbols `ScreenItem` and `ScreenItems` appear **zero times** in every
  classic Openness assembly (V16, V18 and V21 were all checked);
* `Siemens.Engineering.Hmi.Screen.ScreenComposition` has **no `Create(name)`** —
  only `CreateFrom(MasterCopy)` and `Import(Simatic ML XML)`.

So on a classic panel, Openness can manage screens, tags, connections, text and
graphic lists, screen templates/popups/slide-ins, instantiate library master
copies, import and export screen XML, and compile — but it **cannot place a
widget on a screen**.

## How to tell which one you have

* Panel name starts with **MTP** → Unified → supported.
* Panel name starts with **KTP / TP / OP / MP** → classic → not supported.
* Or call the `tia_list_devices` tool: a classic panel makes the server report
  `No WinCC Unified HMI found in this project`.

## Control subset differs per panel

The panel itself gates which controls may be created. Probing a **7" Unified
Basic** panel against the 43 control types this server knows:

* **34 accepted** — including `HmiButton`, `HmiIOField`, `HmiSymbolicIOField`,
  `HmiTextBox`, `HmiText`, `HmiRectangle`, `HmiCircle`, `HmiLine`, `HmiClock`,
  `HmiBar`, `HmiGauge`, `HmiSlider`, `HmiToggleSwitch`, `HmiListBox`,
  `HmiCheckBoxGroup`, `HmiRadioButtonGroup`, `HmiAlarmControl`,
  `HmiAlarmIndicator`, `HmiTrendControl`.
* **9 rejected** — `HmiLabel`, `HmiMediaControl`, `HmiProcessControl`,
  `HmiFunctionTrendControl`, `HmiTrendCompanion`, and the four
  `HmiProcessDiagnosis*Control` types. Whether a Comfort panel accepts them was
  not tested; use `HmiText` for static labels on a Basic panel.

Call `tia_screen_item_types` at runtime for the live list, and note that a type
being listed there does not guarantee the connected panel accepts it — a
rejected `Create<T>` comes back as "Not supported".
