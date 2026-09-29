"""TIA Portal Openness bridge.

Loads the Siemens Openness assemblies into the CLR via pythonnet and exposes a
small, path-addressed object model on top of them.

Object model (WinCC Unified, TIA V21):

    HmiSoftware
      Screens        HmiScreenComposition     -> HmiScreen
        ScreenItems  HmiScreenItemBaseComposition -> HmiButton / HmiIOField / ...
      ScreenGroups   HmiScreenGroupComposition -> HmiScreenGroup
      TagTables      HmiTagTableComposition    -> HmiTagTable
        Tags         HmiTagComposition         -> HmiTag
      Connections    HmiConnectionComposition  -> HmiConnection

Openness is not thread safe, so every CLR call must run on the single worker
thread; `run_on_openness_thread` is the only supported way in.
"""

from __future__ import annotations

import glob
import os
import re
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------
# Assembly bootstrap
# --------------------------------------------------------------------------

def _discover_api_dir() -> str:
    """Newest Openness reference-assembly folder installed on this machine.

    Nothing is hardcoded to one machine: the candidate roots come from the TIA
    installations registered with Windows, plus Siemens' default program folder.
    Set TIA_OPENNESS_API_DIR to skip the search.
    """
    import winreg  # noqa: PLC0415

    roots: list[str] = [os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                                     "Siemens", "Automation")]

    uninstall_keys = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    for key_path in uninstall_keys:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                for index in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        with winreg.OpenKey(key, winreg.EnumKey(key, index)) as entry:
                            name, _ = winreg.QueryValueEx(entry, "DisplayName")
                            # Entries appear under both short and long product
                            # names: "TIA Portal Project Server V16" and
                            # "Siemens Totally Integrated Automation Portal V21".
                            if not any(
                                marker in str(name)
                                for marker in ("TIA Portal", "Totally Integrated")
                            ):
                                continue
                            location, _ = winreg.QueryValueEx(entry, "InstallLocation")
                    except OSError:
                        continue
                    if location:
                        roots.append(str(location))
        except OSError:
            continue

    candidates: list[str] = []
    for root in roots:
        # Walk up from a component folder until a Portal V* folder appears.
        parts = os.path.normpath(root).split(os.sep)
        for depth in range(len(parts), 1, -1):
            parent = os.sep.join(parts[:depth])
            candidates.extend(
                glob.glob(os.path.join(parent, "Portal V*", "PublicAPI", "V*", "net48"))
            )
            candidates.extend(glob.glob(os.path.join(parent, "PublicAPI", "V*", "net48")))

    usable = [path for path in candidates if os.path.isfile(
        os.path.join(path, "Siemens.Engineering.Base.dll"))]
    if not usable:
        return ""
    return max(usable, key=_version_key)


def _version_key(path: str) -> int:
    """Sort key from a version in the path, e.g. ...\\V21\\net48 -> 21."""
    numbers = [int(part[1:]) for part in path.replace("\\", "/").split("/")
               if re.fullmatch(r"V\d+", part)]
    return max(numbers) if numbers else 0


API_DIR = os.environ.get("TIA_OPENNESS_API_DIR") or _discover_api_dir()


def _probe_dirs() -> list[str]:
    """Directories the CLR should search for referenced Siemens assemblies.

    The reference assemblies in PublicAPI/<version>/net48 reference
    Siemens.Engineering.Contract, which the installation ships one level up
    under Bin/PublicAPI instead. Without it pythonnet cannot build the Python
    type for any class that derives from a type in that assembly.
    """
    dirs = [API_DIR]
    portal_root = os.path.dirname(os.path.dirname(os.path.dirname(API_DIR.rstrip("\\/"))))
    dirs.append(os.path.join(portal_root, "Bin", "PublicAPI"))
    extra = os.environ.get("TIA_OPENNESS_EXTRA_DIRS", "")
    dirs.extend(part for part in extra.split(os.pathsep) if part)
    return dirs


# Order matters only in that Base must be present; the rest are loaded so the
# CLR can resolve device/hardware types referenced by a project.
_ASSEMBLIES = (
    "Siemens.Engineering.Base.dll",
    "Siemens.Engineering.Step7.dll",
    "Siemens.Engineering.WinCC.dll",
    "Siemens.Engineering.WinCCUnified.dll",
    "Siemens.Engineering.Safety.dll",
    "Siemens.Engineering.SafetyValidation.dll",
    "Siemens.Engineering.Startdrive.dll",
)

_bootstrap_lock = threading.Lock()
_bootstrapped = False

# CLR types, filled in by bootstrap(). Declared here so type checkers see them.
TiaPortal: Any = None
TiaPortalMode: Any = None
SoftwareContainer: Any = None
HmiSoftware: Any = None
ICompilable: Any = None
MultilingualText: Any = None
FileInfo: Any = None
DirectoryInfo: Any = None
SystemColor: Any = None
SystemEnum: Any = None


class OpennessError(RuntimeError):
    """Any failure originating from TIA Portal Openness."""


def bootstrap() -> None:
    """Load the Openness assemblies. Idempotent."""
    global _bootstrapped
    global TiaPortal, TiaPortalMode, SoftwareContainer, HmiSoftware, ICompilable
    global MultilingualText
    global FileInfo, DirectoryInfo, SystemColor, SystemEnum

    with _bootstrap_lock:
        if _bootstrapped:
            return
        if not API_DIR or not os.path.isdir(API_DIR):
            raise OpennessError(
                "No TIA Portal Openness installation found"
                + (f" at {API_DIR}" if API_DIR else "")
                + ".\nInstall TIA Portal with the Openness option, or point "
                "TIA_OPENNESS_API_DIR at the 'PublicAPI\\V<version>\\net48' folder "
                "of an existing installation."
            )

        # The Siemens assemblies reference each other by simple name, so their
        # folders must be both on PATH (native deps) and resolvable by the CLR.
        probe_dirs = _probe_dirs()
        os.environ["PATH"] = os.pathsep.join([*probe_dirs, os.environ.get("PATH", "")])
        for directory in probe_dirs:
            if directory not in sys.path:
                sys.path.append(directory)

        import clr  # noqa: PLC0415  (must be imported after PATH is set)

        from System import AppDomain, Enum, Reflection, ResolveEventHandler  # noqa: PLC0415
        from System.IO import DirectoryInfo as _DirectoryInfo  # noqa: PLC0415
        from System.IO import FileInfo as _FileInfo  # noqa: PLC0415

        def _resolve(sender, args):
            name = args.Name.split(",")[0]
            for directory in probe_dirs:
                candidate = os.path.join(directory, name + ".dll")
                if os.path.exists(candidate):
                    return Reflection.Assembly.LoadFrom(candidate)
            return None

        # Keep a reference alive; an unreferenced delegate gets collected and
        # the handler silently stops firing.
        handler = ResolveEventHandler(_resolve)
        AppDomain.CurrentDomain.AssemblyResolve += handler
        globals()["_assembly_resolve_handler"] = handler

        loaded = 0
        for name in _ASSEMBLIES:
            path = os.path.join(API_DIR, name)
            if os.path.exists(path):
                clr.AddReference(path)
                loaded += 1
        if not loaded:
            raise OpennessError(f"No Openness assemblies found in {API_DIR}")

        try:
            clr.AddReference("System.Drawing")
            from System.Drawing import Color as _Color  # noqa: PLC0415

            SystemColor = _Color
        except Exception:
            SystemColor = None

        from Siemens.Engineering import MultilingualText as _MultilingualText  # noqa: PLC0415
        from Siemens.Engineering import TiaPortal as _TiaPortal  # noqa: PLC0415
        from Siemens.Engineering import TiaPortalMode as _TiaPortalMode  # noqa: PLC0415
        from Siemens.Engineering.Compiler import ICompilable as _ICompilable  # noqa: PLC0415
        from Siemens.Engineering.HW.Features import (  # noqa: PLC0415
            SoftwareContainer as _SoftwareContainer,
        )
        from Siemens.Engineering.HmiUnified import HmiSoftware as _HmiSoftware  # noqa: PLC0415

        TiaPortal = _TiaPortal
        TiaPortalMode = _TiaPortalMode
        SoftwareContainer = _SoftwareContainer
        HmiSoftware = _HmiSoftware
        ICompilable = _ICompilable
        MultilingualText = _MultilingualText
        FileInfo = _FileInfo
        DirectoryInfo = _DirectoryInfo
        SystemEnum = Enum

        _bootstrapped = True


def display_version() -> str:
    """The TIA Portal version these assemblies belong to, e.g. 'V21'."""
    return os.path.basename(os.path.dirname(API_DIR.rstrip("\\/")))


# --------------------------------------------------------------------------
# Serial execution scope
# --------------------------------------------------------------------------

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tia-hmi")


def run_on_openness_thread(func, *args):
    """Run `func` on the single Openness thread and return its result."""
    return _executor.submit(func, *args).result()


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------


@dataclass
class PortalInstance:
    id: int
    mode: str
    version: str
    project_path: str | None


def list_portal_instances() -> list[PortalInstance]:
    """Every running TIA Portal process Openness can see."""
    bootstrap()
    return [
        PortalInstance(
            id=int(process.Id),
            mode=str(process.Mode),
            version=_installed_software(process),
            project_path=_safe_str(process, "ProjectPath") or None,
        )
        for process in TiaPortal.GetProcesses()
    ]


def _installed_software(process) -> str:
    """Readable product list, e.g. 'STEP 7 Professional V21, WinCC Unified V21'.

    InstalledSoftware is a collection of TiaPortalProduct, so stringifying it
    yields a CLR type name rather than anything useful.
    """
    try:
        products = process.InstalledSoftware
    except Exception:
        return ""
    if products is None:
        return ""
    if isinstance(products, str):
        return products
    try:
        names = []
        for product in products:
            name = _safe_str(product, "Name")
            version = _safe_str(product, "Version")
            names.append(" ".join(part for part in (name, version) if part))
        return ", ".join(name for name in names if name)
    except Exception:
        return str(products)


def _safe_str(obj, attribute: str) -> str:
    try:
        value = getattr(obj, attribute)
    except Exception:
        return ""
    if value is None:
        return ""
    return str(value)


class Session:
    """One live Openness connection to a TIA Portal instance and a project."""

    def __init__(self) -> None:
        self.portal: Any = None
        self.project: Any = None
        # True only when this session opened the project itself. A project that
        # was already open - the normal case, TIA is running with the project in
        # its UI - must never be closed through Openness.
        self._project_owned = False

    # -- lifecycle --------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self.portal is not None

    def connect(
        self,
        instance_id: int | None = None,
        mode: str = "without_ui",
        project_path: str | None = None,
    ) -> str:
        """Attach to a running instance, or start a new one, then open a project.

        Attaching is always preferred: TIA holds a project open exclusively, so
        a second instance cannot open a project the first one already has.
        """
        if self.connected:
            raise OpennessError(
                "Already connected. Call tia_disconnect first, "
                "or use tia_open_project to switch projects."
            )
        bootstrap()

        processes = list(TiaPortal.GetProcesses())
        chosen = self._choose_instance(processes, instance_id, project_path)

        attached_to = None
        if chosen is not None:
            project_path = project_path or (_safe_str(chosen, "ProjectPath") or None)
            self.portal = chosen.Attach()
            attached_to = int(chosen.Id)
        else:
            ui_mode = (
                TiaPortalMode.WithUserInterface
                if mode == "with_ui"
                else TiaPortalMode.WithoutUserInterface
            )
            self.portal = TiaPortal(ui_mode)

        if project_path:
            self.project = self._open_project(project_path)

        parts = [f"connected to TIA Portal {display_version()}"]
        parts.append(
            f"attached to running instance {attached_to}"
            if attached_to
            else f"started new instance ({mode})"
        )
        parts.append(
            f"project '{self.project.Name}'" if self.project is not None else "no project open"
        )
        return "; ".join(parts)

    @staticmethod
    def _choose_instance(processes: list, instance_id: int | None, project_path: str | None):
        if instance_id is not None:
            for process in processes:
                if int(process.Id) == instance_id:
                    return process
            raise OpennessError(
                f"No TIA Portal instance with id {instance_id}. "
                f"Running: {[int(p.Id) for p in processes] or 'none'}"
            )
        if len(processes) == 1:
            return processes[0]
        if project_path is not None:
            want = os.path.splitext(os.path.basename(os.path.abspath(project_path)))[0]
            for process in processes:
                open_path = _safe_str(process, "ProjectPath")
                if open_path and os.path.splitext(os.path.basename(open_path))[0] == want:
                    return process
        return None

    def _open_project(self, project_path: str) -> Any:
        """Open a project, or pick it up if the instance already has it open.

        TIA holds a project open exclusively, so re-opening one that this
        instance already has fails outright. Project.Path points at the .ap*
        file, but callers may pass either that or the project folder, so match
        on the normalised path and fall back to the project name.
        """
        want = os.path.abspath(project_path)
        want_key = os.path.normcase(want)
        want_name = os.path.splitext(os.path.basename(want))[0]

        for open_project in self.portal.Projects:
            try:
                current = os.path.abspath(str(open_project.Path.FullName))
            except Exception:
                continue
            if os.path.normcase(current) == want_key:
                self._project_owned = False
                return open_project
            if want_name and os.path.splitext(os.path.basename(current))[0] == want_name:
                self._project_owned = False
                return open_project

        self._project_owned = True
        if os.path.isdir(want):
            return self.portal.Projects.Open(DirectoryInfo(want))
        if not os.path.isfile(want):
            raise OpennessError(f"Project not found: {want}")
        return self.portal.Projects.Open(FileInfo(want))

    def open_project(self, project_path: str) -> str:
        if not self.connected:
            raise OpennessError("Not connected.")
        self.project = self._open_project(project_path)
        return f"project '{self.project.Name}'"

    def save(self) -> str:
        self._require_project()
        self.project.Save()
        return f"saved project '{self.project.Name}'"

    def close_project(self, save: bool = False) -> str:
        """Close the project, but only one this session opened itself.

        Closing a project that TIA already has open leaves it half-closed: it
        stays in the Projects list while its devices become unreachable. Refuse
        rather than do that.
        """
        self._require_project()
        if not self._project_owned:
            raise OpennessError(
                "This project is open in TIA Portal itself, so it is not closed from here. "
                "Close it in the TIA Portal UI."
            )
        name = str(self.project.Name)
        if save:
            self.project.Save()
        self.project.Close()
        self.project = None
        self._project_owned = False
        return f"closed project '{name}'"

    def disconnect(self, save: bool = False) -> str:
        """Release the Openness session, leaving TIA and its project running."""
        notes = []
        if self.project is not None:
            if self._project_owned:
                notes.append(self.close_project(save=save))
            else:
                if save:
                    notes.append(self.save())
                notes.append("released the Openness session; the project stays open in TIA Portal")
        if self.portal is not None:
            self.portal.Dispose()
            self.portal = None
            self.project = None
            self._project_owned = False
        if not notes:
            notes.append("nothing was open")
        return "; ".join(notes)

    def _require_project(self) -> None:
        if not self.connected:
            raise OpennessError("Not connected. Call tia_connect first.")
        if self.project is None:
            raise OpennessError("No project open. Pass project_path to tia_connect or tia_open_project.")

    # -- devices ----------------------------------------------------------

    def devices(self) -> list[Any]:
        self._require_project()
        return list(self.project.Devices)

    def hmi_devices(self) -> dict[str, Any]:
        """Map HMI device name -> HmiSoftware, for every HMI in the project."""
        found: dict[str, Any] = {}
        for device in self.devices():
            software = find_hmi_software(device)
            if software is not None:
                found[str(device.Name)] = software
        return found

    def hmi_software(self, device_name: str | None = None) -> Any:
        hmis = self.hmi_devices()
        if device_name is None:
            return _only_one(hmis, "HMI")
        return _pick(hmis, device_name, "HMI")

    def hmi_compile_target(self, device_name: str | None = None) -> Any:
        """The Device whose compile service builds an HMI.

        Only Device offers ICompilable. HmiSoftware is not even a service
        provider, and its DeviceItem and SoftwareContainer return None.
        """
        self._require_project()
        found: dict[str, Any] = {}
        for device in self.project.Devices:
            for item in _walk_device_items(device):
                container = _software_container(item)
                software = getattr(container, "Software", None) if container is not None else None
                if isinstance(software, HmiSoftware):
                    found[str(device.Name)] = device
                    break
        if device_name is None:
            return _only_one(found, "HMI device")
        return _pick(found, device_name, "HMI device")


def _only_one(mapping: dict, what: str) -> Any:
    if not mapping:
        raise OpennessError(
            f"No WinCC Unified {what} found in this project. "
            "This server only drives Unified (MTP) targets."
        )
    if len(mapping) > 1:
        raise OpennessError(f"Project has {len(mapping)} {what}s; name one of: {', '.join(mapping)}")
    return next(iter(mapping.values()))


def _pick(mapping: dict, name: str, what: str) -> Any:
    if not mapping:
        raise OpennessError(f"No WinCC Unified {what} found in this project.")
    for key, value in mapping.items():
        if key == name:
            return value
    raise OpennessError(f"No {what} named '{name}'. Available: {', '.join(mapping)}")


def find_hmi_software(device) -> Any:
    """The HmiSoftware of a device, or None if the device is not an HMI.

    HmiSoftware is not an IEngineeringService, so GetService cannot produce it;
    it is reached through the device item's SoftwareContainer, the same way
    PlcSoftware is.
    """
    for item in _walk_device_items(device):
        container = _software_container(item)
        if container is None:
            continue
        software = getattr(container, "Software", None)
        if isinstance(software, HmiSoftware):
            return software
    return None


def _software_container(device_item) -> Any:
    try:
        return device_item.GetService[SoftwareContainer]()
    except Exception:
        pass
    try:
        return SoftwareContainer(device_item)
    except Exception:
        return None


def _walk_device_items(item) -> Iterator[Any]:
    yield item
    try:
        children = item.DeviceItems
    except Exception:
        return
    for child in children:
        yield from _walk_device_items(child)


# --------------------------------------------------------------------------
# Path resolution
# --------------------------------------------------------------------------
#
#   <area>/<name>[...]                 area of the (single) HMI in the project
#   <hmiDevice>/<area>/<name>[...]     explicit HMI, needed when there is more
#                                      than one
#
# Areas: screens, screengroups, tagtables, tagtablegroups, connections,
#        textlists, graphiclists
# Sub-areas: screens/<s>/items, tagtables/<t>/tags

_AREAS = {
    "screens": lambda hmi: hmi.Screens,
    "screengroups": lambda hmi: hmi.ScreenGroups,
    "tagtables": lambda hmi: hmi.TagTables,
    "tagtablegroups": lambda hmi: hmi.TagTableGroups,
    "connections": lambda hmi: hmi.Connections,
    "textlists": lambda hmi: hmi.HmiTextLists,
    "graphiclists": lambda hmi: hmi.HmiGraphicLists,
}

_SUB_AREAS = {
    "screens": {"items": lambda screen: screen.ScreenItems},
    "tagtables": {"tags": lambda table: table.Tags},
    "screengroups": {
        "screens": lambda group: group.Screens,
        "groups": lambda group: group.Groups,
    },
    "tagtablegroups": {
        "tagtables": lambda group: group.TagTables,
        "groups": lambda group: group.Groups,
    },
}


def resolve(path: str, session: Session | None = None) -> Any:
    """Resolve a path to an Openness object."""
    session = session or _current_session
    segments = [s for s in path.replace("\\", "/").split("/") if s]
    if not segments:
        raise OpennessError("Empty path.")

    # A leading segment that is not an area name is an HMI device name.
    hmi_device = None
    if segments[0] not in _AREAS:
        hmi_device = segments.pop(0)
        if not segments:
            raise OpennessError(
                f"Path must continue past the HMI name '{hmi_device}'; "
                f"known areas: {', '.join(_AREAS)}"
            )
    hmi = session.hmi_software(hmi_device)

    if not segments:
        return hmi

    area = segments.pop(0)
    if area not in _AREAS:
        raise OpennessError(f"Unknown area '{area}'. Known: {', '.join(_AREAS)}")

    composition = _AREAS[area](hmi)
    if not segments:
        return composition

    current = _find_in(composition, segments.pop(0), area)

    while segments:
        sub = segments.pop(0)
        if sub not in _SUB_AREAS.get(area, {}):
            known = ", ".join(_SUB_AREAS.get(area, {})) or "none"
            raise OpennessError(
                f"'{area}' has no sub-area '{sub}' (known: {known}). "
                f"Current object: {type(current).__name__}"
            )
        composition = _SUB_AREAS[area][sub](current)
        if not segments:
            return composition
        current = _find_in(composition, segments.pop(0), sub)

    return current


def _find_in(composition, name: str, what: str) -> Any:
    try:
        found = composition.Find(name)
        if found is not None:
            return found
    except Exception:
        pass
    for item in composition:
        if _safe_str(item, "Name") == name:
            return item
    raise OpennessError(f"No '{name}' in {what}.")


# --------------------------------------------------------------------------
# Attributes
# --------------------------------------------------------------------------


def attribute_infos(obj) -> list[Any]:
    """The EngineeringAttributeInfo list of an object.

    The documentation types GetAttributeInfos as a property, but pythonnet
    binds it as a method on every object seen so far; accept both shapes.
    """
    try:
        infos = obj.GetAttributeInfos
    except Exception:
        return []
    if callable(infos):
        try:
            infos = infos()
        except Exception:
            return []
    try:
        return list(infos)
    except Exception:
        return []


def attribute_names(obj) -> list[str]:
    return [str(info.Name) for info in attribute_infos(obj)]


def _attribute_info(obj, name: str) -> Any:
    for info in attribute_infos(obj):
        if str(info.Name) == name:
            return info
    return None


def declared_supported_types(info: Any) -> list[Any]:
    """The CLR types an EngineeringAttributeInfo declares, nulls dropped.

    Unified widgets declare a single null entry for their colour properties
    instead of System.Drawing.Color, so an unfiltered list reads as ['None']
    and hides the fact that the attribute declares no type at all. Reading an
    info directly is what a caller walking attribute_infos already has.
    """
    try:
        return [t for t in info.SupportedTypes if t is not None]
    except Exception:
        return []


def supported_types(obj, name: str) -> list[Any]:
    """The CLR types an attribute accepts, with the null entries dropped."""
    info = _attribute_info(obj, name)
    if info is None:
        return []
    return declared_supported_types(info)


def declared_type(obj, name: str) -> Any:
    """The CLR type a property is declared with, read off the .NET type itself.

    SupportedTypes cannot answer this: it is a null entry for every colour
    property, and empty for many others. Reflection can, and the difference
    matters - it is what separates BackColor (a Color) from OutputFormat
    (a String) when a value looks like "#RRGGBB".
    """
    try:
        info = obj.GetType().GetProperty(name)
    except Exception:
        return None
    return getattr(info, "PropertyType", None) if info is not None else None


def to_clr(value: Any, obj: Any, name: str) -> Any:
    """Coerce a JSON value into whatever CLR type the property expects."""
    if value is None or not isinstance(value, (str, list, tuple)):
        return value

    types = supported_types(obj, name)
    type_names = {str(t) for t in types}
    declared = str(declared_type(obj, name) or "")

    # "#RRGGBB", "255,0,0" or [r, g, b] -> System.Drawing.Color. A colour
    # property declares no type at all, so the declared CLR type is what this
    # keys on - a String property holding "1,2,3" must keep it. When nothing is
    # known about the property, these shapes are still worth a try.
    unknown = not declared and not type_names
    if SystemColor is not None and ("Color" in declared or unknown):
        converted = _as_color(value)
        if converted is not None:
            return converted

    # Enum member name -> the enum value itself.
    if isinstance(value, str):
        for candidate in types:
            try:
                if candidate.IsEnum:
                    return SystemEnum.Parse(candidate, value)
            except Exception:
                continue

    return value


def _as_color(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return SystemColor.FromArgb(int(value[0]), int(value[1]), int(value[2]))
        except Exception:
            return None
    text = str(value).strip()
    try:
        if text.startswith("#") and len(text) == 7:
            return SystemColor.FromArgb(
                int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
            )
        if text.count(",") == 2:
            r, g, b = (int(part) for part in text.split(","))
            return SystemColor.FromArgb(r, g, b)
    except Exception:
        return None
    return None


def get_attributes(obj, names: list[str] | None = None) -> dict[str, Any]:
    """Read properties, preferring the typed CLR property over GetAttribute."""
    if names is None:
        names = attribute_names(obj)
    out: dict[str, Any] = {}
    for name in names:
        try:
            out[name] = _plain(getattr(obj, name))
            continue
        except AttributeError:
            pass
        except Exception as exc:
            out[name] = f"<unreadable: {str(exc).splitlines()[0]}>"
            continue
        try:
            out[name] = _plain(obj.GetAttribute(name))
        except Exception as exc:
            out[name] = f"<unreadable: {str(exc).splitlines()[0]}>"
    return out


def set_attributes(obj, values: dict[str, Any]) -> dict[str, str]:
    """Set each property, reporting per-name success or failure.

    Writes go through the typed CLR property. IEngineeringObject.SetAttribute
    is deliberately not used: on WinCC Unified objects it raises
    NonRecoverableException and takes the whole Openness session down with it.

    A value of ``{"$ref": "<path>"}`` is resolved to another Openness object
    first, which is how object-valued properties (a tag's Connection, a
    dynamization's Tag) are assigned.
    """
    results: dict[str, str] = {}
    for name, value in values.items():
        try:
            if isinstance(value, dict) and "$ref" in value:
                value = resolve(str(value["$ref"]))
            _assign(obj, name, value)
            results[name] = "ok"
        except Exception as exc:
            results[name] = f"failed: {_brief(exc)}"
    return results


def _brief(exc: Exception, limit: int = 320) -> str:
    """One readable line from an Openness exception.

    Siemens puts the call site on the first line and the actual reason on the
    second, so the first line alone is useless.
    """
    joined = " | ".join(line.strip() for line in str(exc).splitlines() if line.strip())
    return joined[:limit]


def _assign(obj, name: str, value: Any) -> None:
    """Assign one property, unwrapping the MultilingualText of text properties.

    Text-valued properties (HmiButton.Text, HmiText.Text, ...) are read-only and
    hand back a MultilingualText, so the words go into that object instead.
    """
    try:
        setattr(obj, name, to_clr(value, obj, name))
        return
    except (TypeError, AttributeError) as exc:
        nested = getattr(obj, name, None)
        if isinstance(nested, MultilingualText):
            set_caption(nested, str(value))
            return
        raise exc


# A caption is stored as a body/p fragment. MultilingualTextItem.Text rejects a
# bare string outright ("has an invalid format"), and MultilingualText.Text is a
# dead end: it accepts the write, reports success, and changes nothing.
_CAPTION_MARKUP = "<body><p>{}</p></body>"


def set_caption(text_object, text: str) -> None:
    """Write a caption into a MultilingualText, in every language it holds."""
    markup = text if text.lstrip().startswith("<") else _CAPTION_MARKUP.format(text)
    items = list(text_object.Items)
    if not items:
        raise OpennessError(
            f"Cannot write the caption {text!r}: the text object has no language entry."
        )
    for item in items:
        item.Text = markup


def _plain(value: Any) -> Any:
    """Convert a CLR value into something JSON-serialisable."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    try:
        return str(value)
    except Exception:
        return repr(value)


# --------------------------------------------------------------------------
# The single live session
# --------------------------------------------------------------------------

_current_session = Session()


def session() -> Session:
    return _current_session


# --------------------------------------------------------------------------
# Convenience wrappers used by the MCP tools
# --------------------------------------------------------------------------


_SCREEN_ITEM_MODULES = (
    "Siemens.Engineering.HmiUnified.UI.Widgets",
    "Siemens.Engineering.HmiUnified.UI.Shapes",
    "Siemens.Engineering.HmiUnified.UI.Controls",
    "Siemens.Engineering.HmiUnified.UI.Screens",
)

_screen_item_catalogue: dict[str, Any] | None = None


def screen_item_types() -> dict[str, Any]:
    """Every CLR type that can be created in a screen's ScreenItems composition."""
    global _screen_item_catalogue
    if _screen_item_catalogue is not None:
        return _screen_item_catalogue

    import importlib  # noqa: PLC0415

    import clr  # noqa: PLC0415

    from Siemens.Engineering.HmiUnified.UI.Base import HmiScreenItemBase  # noqa: PLC0415

    base = clr.GetClrType(HmiScreenItemBase)
    assembly = base.Assembly
    try:
        clr_types = assembly.GetTypes()
    except Exception as exc:
        clr_types = [t for t in exc.Types if t is not None]

    catalogue: dict[str, Any] = {}
    for clr_type in clr_types:
        if not _is_creatable_screen_item(clr_type, base):
            continue
        module = importlib.import_module(clr_type.Namespace)
        python_class = getattr(module, clr_type.Name, None)
        if python_class is not None:
            catalogue[clr_type.Name] = python_class

    _screen_item_catalogue = catalogue
    return catalogue


def _is_creatable_screen_item(clr_type, base) -> bool:
    """Whether Create<T>() accepts this type.

    The abstract levels of the control hierarchy are not flagged IsAbstract,
    but Siemens names every one of them '*Base' (HmiWidgetBase, HmiShapeBase,
    HmiTextWidgetBase, ...) while no concrete control is. Concrete controls can
    still be parents of other controls - HmiToggleSwitch derives from
    HmiButton, HmiSlider from HmiBar - so name suffix is the only usable signal.
    """
    try:
        return (
            clr_type.Namespace in _SCREEN_ITEM_MODULES
            and clr_type.IsPublic
            and not clr_type.IsAbstract
            and not clr_type.IsInterface
            and not clr_type.Name.endswith("Base")
            and base.IsAssignableFrom(clr_type)
        )
    except Exception:
        return False


def create_screen_item(screen_path: str, item_type: str, name: str) -> Any:
    catalogue = screen_item_types()
    if item_type not in catalogue:
        raise OpennessError(
            f"Unknown screen item type '{item_type}'. Known: {', '.join(sorted(catalogue))}"
        )
    screen = resolve(screen_path)
    return screen.ScreenItems.Create[catalogue[item_type]](name)


def bind_tag(item_path: str, property_name: str, tag_path: str) -> str:
    """Bind an HMI tag to one property of a screen item."""
    item = resolve(item_path)
    tag = resolve(tag_path)
    bind_tag_to(item, property_name, tag)
    return f"bound {tag_path} to {property_name} of {item_path}"


def bind_tag_to(item, property_name: str, tag):
    """Point one property of a widget at an HMI tag.

    Two quirks of this API:
      * the widget property cannot take the tag directly - ProcessValue and
        friends are declared as String - so a dynamization is the only route;
      * the string DynamizationBaseComposition.Create<T>() takes is the
        *property* name, not a name for the new object, and TagDynamization.Tag
        is itself a String holding the tag's name, not the tag object.
    """
    from Siemens.Engineering.HmiUnified.UI.Dynamization import TagDynamization  # noqa: PLC0415

    dynamization = item.Dynamizations.Create[TagDynamization](property_name)
    results = set_attributes(dynamization, {"Tag": str(tag.Name)})
    bad = {key: value for key, value in results.items() if value != "ok"}
    if bad:
        raise OpennessError(
            f"created the dynamization for '{property_name}' but could not attach the tag: "
            f"{bad}"
        )
    return dynamization


# --------------------------------------------------------------------------
# Panels
# --------------------------------------------------------------------------


# Panel families that resolve to WinCC Unified. Classic panels (KTP/TP/OP/MP)
# are a different software target that Openness cannot author at all.
PANEL_FAMILIES = ("MTP400", "MTP700", "MTP1000", "MTP1200", "MTP1500", "MTP1900", "MTP2200")


def list_panel_models() -> list[dict[str, str]]:
    """Every Unified panel the installed hardware catalog offers.

    Polled from the catalog rather than hard-coded, so the list matches the
    installation. ``type_identifier`` is what add_hmi_device takes.
    """
    if _current_session.portal is None:
        raise OpennessError("Not connected. Call tia_connect first.")
    catalog = _current_session.portal.HardwareCatalog

    models: dict[str, dict[str, str]] = {}
    for family in PANEL_FAMILIES:
        for entry in catalog.Find(family):
            article = _safe_str(entry, "ArticleNumber")
            identifier = _safe_str(entry, "TypeIdentifier")
            if article and identifier and article not in models:
                models[article] = {
                    "article_number": article,
                    "type_identifier": identifier,
                    "name": _safe_str(entry, "TypeName"),
                    "catalog_path": _safe_str(entry, "CatalogPath"),
                }
    return [models[article] for article in sorted(models)]


def add_hmi_device(type_identifier: str, name: str) -> dict[str, Any]:
    """Create an HMI device in the open project.

    The type identifier comes from list_panel_models, or from the
    ``OrderNumber:<article>/<version>`` form. This writes to the project, so ask
    which model is wanted first. Nothing reaches disk until the project is saved.
    """
    _current_session._require_project()
    device = _current_session.project.Devices.CreateWithItem(type_identifier, name, name)
    software = find_hmi_software(device)
    return {
        "name": str(device.Name),
        "type_identifier": type_identifier,
        "device_items": [str(item.Name) for item in device.DeviceItems],
        "is_hmi": software is not None,
        "screens": [str(screen.Name) for screen in software.Screens] if software is not None else [],
    }


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------


def _read(obj, name: str) -> Any:
    """One property, or None when this object does not have it.

    Widgets differ in what they expose - an HmiButton has no
    HorizontalTextAlignment, an HmiIOField has no Text - so every read of an
    optional property goes through here.
    """
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _rgb(value: Any) -> tuple[int, int, int] | None:
    """(r, g, b) out of a System.Drawing.Color, or None when nothing is painted.

    A fully transparent colour leaves whatever is behind showing through, which
    is exactly the case the checker composites a background for.
    """
    if value is None:
        return None
    try:
        if int(value.A) == 0:
            return None
        return (int(value.R), int(value.G), int(value.B))
    except Exception:
        return None


def _caption(item) -> str:
    """The raw stored caption, markup and all. '' when the widget has none."""
    try:
        entries = list(item.Text.Items)
    except Exception:
        return ""
    return str(entries[0].Text) if entries else ""


def _geometry(item) -> dict[str, int]:
    return {
        key.lower(): int(_read(item, key) or 0) for key in ("Left", "Top", "Width", "Height")
    }


def _font_size(item) -> float | None:
    """Font.Size, which lives on an HmiFontPart rather than on the widget."""
    font = _read(item, "Font")
    try:
        return float(_read(font, "Size")) if font is not None else None
    except (TypeError, ValueError):
        return None


def _dynamization_flags(item) -> dict[str, bool]:
    """Which of a widget's properties a tag drives.

    The dynamization carries the property it drives in PropertyName - there is
    no Name property on a TagDynamization.
    """
    driven = set()
    for dynamization in list(_read(item, "Dynamizations") or []):
        name = _read(dynamization, "PropertyName")
        if name:
            driven.add(str(name))
    return {"bound": "ProcessValue" in driven, "text_bound": "Text" in driven}


def read_layout(screen_path: str) -> dict[str, Any]:
    """Everything the layout checker and the renderer need, read off one screen.

    Items come back in z-order, bottom first, which is the order ScreenItems
    yields and the order background compositing depends on. Invisible items are
    left out and named in ``hidden_items``: the operator cannot see them, so
    reporting them would be noise.
    """
    from layout import strip_markup  # noqa: PLC0415  (pure helper, no Openness)

    screen = resolve(screen_path)
    items: list[dict[str, Any]] = []
    hidden: list[str] = []

    for item in screen.ScreenItems:
        if _read(item, "Visible") is False:
            hidden.append(str(item.Name))
            continue
        items.append(
            {
                "name": str(item.Name),
                "type": type(item).__name__,
                **_geometry(item),
                "back_color": _rgb(_read(item, "BackColor")),
                "fore_color": _rgb(_read(item, "ForeColor")),
                "border_color": _rgb(_read(item, "BorderColor")),
                "border_width": _read(item, "BorderWidth") or 0,
                "text": strip_markup(_caption(item)),
                "font_size": _font_size(item),
                "h_align": _read(item, "HorizontalTextAlignment"),
                "v_align": _read(item, "VerticalTextAlignment"),
                **_dynamization_flags(item),
            }
        )

    return {
        "screen": str(screen.Name),
        "panel": {"width": int(screen.Width), "height": int(screen.Height)},
        "screen_bg": _rgb(_read(screen, "BackColor")),
        "items": items,
        "hidden_items": hidden,
    }


def read_layouts(screen_paths: list[str] | None = None) -> list[dict[str, Any]]:
    """read_layout for several screens; every screen in the HMI when none named."""
    if screen_paths is None:
        screen_paths = [f"screens/{screen.Name}" for screen in _current_session.hmi_software().Screens]
    return [read_layout(path) for path in screen_paths]


def export_tags(directory: str, tag_table: str | None = None) -> str:
    """Export HMI tags to XLSX. Screens cannot be exported; Unified has no API for it."""
    target = DirectoryInfo(os.path.abspath(directory))
    if not os.path.isdir(target.FullName):
        os.makedirs(target.FullName, exist_ok=True)

    if tag_table:
        table = resolve(f"tagtables/{tag_table}")
        table.Tags.Export(target)
        return f"exported tags of '{tag_table}' to {target.FullName}"

    exported = []
    for table in _current_session.hmi_software().TagTables:
        table.Tags.Export(target)
        exported.append(str(table.Name))
    return f"exported tags of {len(exported)} table(s) to {target.FullName}: {', '.join(exported)}"


def compile_hmi_software(hmi_device: str | None = None) -> dict[str, Any]:
    device = _current_session.hmi_compile_target(hmi_device)
    result = device.GetService[ICompilable]().Compile()
    messages: list[dict[str, str]] = []
    _collect_compiler_messages(result, messages)
    return {
        "state": str(result.State),
        "errors": int(result.ErrorCount),
        "warnings": int(result.WarningCount),
        "messages": messages[:60],
    }


def _collect_compiler_messages(node, out: list[dict[str, str]], depth: int = 0) -> None:
    """Flatten the compiler result tree.

    The top-level message carries the error count but an empty Description; the
    text that says what actually went wrong sits in the nested Messages.
    """
    if depth > 6 or len(out) >= 60:
        return
    try:
        children = list(node.Messages)
    except Exception:
        children = []

    description = _safe_str(node, "Description").strip()
    state = _safe_str(node, "State")
    if description or not children:
        out.append({"state": state, "path": _safe_str(node, "Path"), "text": description})

    for child in children:
        _collect_compiler_messages(child, out, depth + 1)
