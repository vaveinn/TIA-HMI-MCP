# TIA Portal Openness API notes

Everything here was established by experiment against a real project, because
the Siemens documentation is silent, wrong, or actively misleading on these
points. **The two rows marked ⚠️ kill the Openness session and take TIA Portal
down with it.**

| Symptom | What is actually going on |
|---|---|
| ⚠️ `obj.SetAttribute(name, value)` | Raises `NonRecoverableException` on WinCC Unified objects, which tears down the whole Openness session and can crash TIA Portal. **Use the typed CLR property** (`item.Left = 40`) — this server never calls `SetAttribute`. |
| ⚠️ `Dynamizations.Create[SomeAbstractBase](…)` | Same `NonRecoverableException`. Only pass a concrete type. |
| `item.Text = "启动"` → "property is read-only" | Text properties are read-only `MultilingualText` objects. The obvious fallback is a trap - see the next two rows. |
| `item.Text.Text = "启动"` → **no error, and no change** | `MultilingualText.Text` accepts the write, drops it, and returns. A caption that reads as written can still be the factory default `文本`. This is how a screen full of widgets ends up with placeholder captions and a clean compile. |
| `item.Text.Items[0].Text = "启动"` → "has an invalid format" | The entry's setter wants a body/p fragment: `<body><p>启动</p></body>`. Go through `tia_openness.set_caption`, which wraps and writes every language entry. |
| A colour write is rejected: `'str' value cannot be converted to System.Drawing.Color` | Colour attributes declare a single **null** entry in `SupportedTypes`, so no declared type name ever contains "Color" and a conversion that keys on the type name never fires. `System.Drawing.Color` itself is available (`clr.AddReference("System.Drawing")`); the fallback has to be "try it when no type is declared". |
| `dynamization.Name` → no attribute | A `TagDynamization` names the property it drives in **`PropertyName`** (`"ProcessValue"`, `"Text"`). `Tag` is the tag's name as a string. |
| `item.FontSize` | No such property. Font details live in an `HmiFontPart`: `item.Font.Size`. |
| `MultilingualText.Text` → no attribute | It holds `Items`, one per language, each with `Language` and `Text`. `Language` stringifies to a type name, not a locale. |
| `button.GetCompositionInfos()` → no attribute | Widgets do not expose it; only some objects do. Guard every call to it. |
| `device.TypeIdentifier` empty after `CreateWithItem` | The `Device` reports none for an HMI; its `DeviceItems` carry the order number. |
| `iofield.ProcessValue = hmiTag` → cannot convert to `System.String` | `ProcessValue` is declared as `String`. Binding is only possible through a dynamization. |
| `Dynamizations.Create[TagDynamization]("t1")` → "Dynamization type not supported" | **The string argument is the property to dynamize, not a name for the new object.** It must be a real dynamizable property of that widget, e.g. `"ProcessValue"`. The error text is misleading. |
| `dyn.Tag = hmiTag` → cannot convert to `System.String` | `TagDynamization.Tag` is also declared as `String`. Assign the tag's **name**, not the tag object. |
| `hmiSoftware.GetService[X]()` → no attribute | `HmiSoftware` is **not** an `IEngineeringServiceProvider`. It is not a service either, so `GetService[HmiSoftware]` cannot even be bound. Reach it through `SoftwareContainer.Software`, the same way `PlcSoftware` is reached. |
| Where does the compile service come from? | Only **`Device`**: `device.GetService[ICompilable]().Compile()`. `HmiSoftware`, its `DeviceItem` and its `SoftwareContainer` all return `None`. |
| `obj.GetAttributeInfos` returns nothing | It is documented as a property but pythonnet binds it as a **method**: `obj.GetAttributeInfos()`. |
| `tag.HmiDataType = "Int"` → error | It does not accept a string. New tags already default to `Int`, so leave it alone; change other types in the TIA UI. |
| Compiler message `Description` is empty | The top-level message carries the counts only. The real text lives in the nested `message.Messages` — this server flattens the tree. |
| `Create<T>` → "Not supported" for some types | The panel gates the control set. See [PANELS.md](PANELS.md). |
| Closing a project that TIA already has open | Leaves it half-closed: it stays in `portal.Projects` while its `Devices` collection goes empty. Never close a project the user has open — this server only closes projects it opened itself. |
| `Project.Path.FullName` | Points at the `.ap*` **file**, not the project folder, despite the name. |
| `TiaPortalProcess.InstalledSoftware` | A `ReadOnlyCollection<TiaPortalProduct>`, so stringifying it yields a CLR type name. Enumerate it and read `Name` / `Version`. |
| `Siemens.Engineering.Contract` not found | pythonnet fails to build the Python type for any class deriving from a type in it. The assembly ships under `<TIA install>\Bin\PublicAPI`, not in `PublicAPI\<version>\net48`; this server adds that folder to the assembly resolution search path automatically. |
| Threading | Openness is not thread safe. Every CLR call in this server is funnelled onto one dedicated worker thread. |

## Creating an empty tag dynamization

```python
from Siemens.Engineering.HmiUnified.UI.Dynamization import TagDynamization

# The argument is the property to dynamize.
dyn = io_field.Dynamizations.Create[TagDynamization]("ProcessValue")
dyn.Tag = "计数_红"        # a string: the tag's name
```

## Creating an HMI device

```python
from Siemens.Engineering import TiaPortal

portal = TiaPortal.GetProcesses()[0].Attach()
project = portal.Projects[0]

# The identifier comes from the hardware catalog, which needs no project open.
for entry in portal.HardwareCatalog.Find("MTP700"):
    print(entry.ArticleNumber, entry.TypeIdentifier)

device = project.Devices.CreateWithItem(
    "OrderNumber:6AV2 123-3GB32-0AW0/21.0.0.0",   # 7" MTP700 Unified Basic
    "HMI_1", "HMI_1",
)
```

The third argument is the device item name; pass the same string twice unless you
want the runtime and the network port named differently. The panel arrives with
**no screens at all** - create the first one with `Screens.Create(name)`. The
version suffix on the identifier is not fussy: the catalog hands back
`.../18.0.0.3` for this panel while `.../21.0.0.0` works just as well.

## Reading a caption

```python
item.Text.Items[0].Text      # '<body><p>启动</p></body>' - the stored form
```

Strip the markup with `layout.strip_markup` before measuring or comparing it.
A widget that was never given a caption holds the placeholder `文本`.

## Environment

| Variable | Purpose |
|---|---|
| `TIA_OPENNESS_API_DIR` | Folder holding the Openness assemblies. Default: `D:\TIAV21\Portal V21\PublicAPI\V21\net48`. |
| `TIA_OPENNESS_EXTRA_DIRS` | Additional assembly search folders, `os.pathsep`-separated. |

Only **TIA Portal V21** has been verified end to end. `Siemens.Engineering.HmiUnified`
exists from V16 onward, so other versions may work once `TIA_OPENNESS_API_DIR` is
pointed at them, but expect the type layout to differ — V21 already splits the
API across `Siemens.Engineering.Base.dll`, `.WinCC.dll` and `.WinCCUnified.dll`
with no single `Siemens.Engineering.dll` in the reference folder.
