"""resolve-ext — DaVinci Resolve MCP extension server.

Fills the 21.1.2 gaps that the mainstream Resolve MCP servers do not cover:
clip effects, effect properties, Paste-Attributes, frame export, folder
lookups, photo albums, node-graph labelling and the camera-comparison layout
workflow.

Deliberately an extension, not a fork: nothing here duplicates another
server's surface, so both run side by side.

Run:
    resolve-ext              # stdio MCP server
    resolve-ext doctor       # check this machine's Resolve setup
    resolve-ext env          # print the env vars an MCP client needs
    resolve-ext --version
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

__version__ = "1.0.2"

# --- locating DaVinci Resolve --------------------------------------------
#
# The scripting API lives in a different place on every platform, and getting
# it wrong is the single most common installation failure. These paths mirror
# what Blackmagic documents and what the mainstream server's platform module
# resolves; an explicit environment variable always wins, because Resolve is
# routinely installed somewhere non-standard.

MACOS_API_CANDIDATES = (
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Developer/Scripting",
)


def find_resolve_paths() -> Dict[str, Optional[str]]:
    """Locate the Resolve scripting API for this platform.

    Returns {"api_path", "lib_path", "modules_path", "platform"}; any value may
    be None when nothing was found, so callers can report precisely which piece
    is missing rather than failing with a bare ImportError.
    """
    import platform as _platform

    system = _platform.system().lower()

    if system == "darwin":
        name = "macos"
        api = next((p for p in MACOS_API_CANDIDATES if os.path.isdir(p)),
                   MACOS_API_CANDIDATES[0])
        lib = ("/Applications/DaVinci Resolve/DaVinci Resolve.app/"
               "Contents/Libraries/Fusion/fusionscript.so")
    elif system == "windows":
        name = "windows"
        programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        programfiles = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        api = os.path.join(programdata, "Blackmagic Design", "DaVinci Resolve",
                           "Support", "Developer", "Scripting")
        lib = os.path.join(programfiles, "Blackmagic Design", "DaVinci Resolve",
                           "fusionscript.dll")
    elif system == "linux":
        name = "linux"
        api = "/opt/resolve/Developer/Scripting"
        lib = "/opt/resolve/libs/fusionscript.so"
    else:
        name = system or "unknown"
        api = lib = None

    # An explicit override wins — but only when it exists, so a stale variable
    # does not mask a working default.
    env_api = os.environ.get("RESOLVE_SCRIPT_API")
    if env_api and os.path.isdir(env_api):
        api = env_api
    env_lib = os.environ.get("RESOLVE_SCRIPT_LIB")
    if env_lib and os.path.isfile(env_lib):
        lib = env_lib

    return {
        "platform": name,
        "api_path": api,
        "lib_path": lib,
        "modules_path": os.path.join(api, "Modules") if api else None,
        "api_exists": bool(api and os.path.isdir(api)),
        "lib_exists": bool(lib and os.path.isfile(lib)),
    }


def apply_resolve_env(verbose: bool = False) -> Dict[str, Optional[str]]:
    """Set RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB / PYTHONPATH if they are unset.

    Existing values are never overwritten, so a user who has configured their
    environment keeps full control.
    """
    paths = find_resolve_paths()
    if paths.get("api_path") and not os.environ.get("RESOLVE_SCRIPT_API"):
        os.environ["RESOLVE_SCRIPT_API"] = paths["api_path"]
    if paths.get("lib_path") and not os.environ.get("RESOLVE_SCRIPT_LIB"):
        os.environ["RESOLVE_SCRIPT_LIB"] = paths["lib_path"]
    mods = paths.get("modules_path")
    if mods and os.path.isdir(mods) and mods not in sys.path:
        sys.path.append(mods)
    if verbose:
        print(f"platform      {paths['platform']}")
        print(f"api_path      {paths['api_path']}  "
              f"({'found' if paths['api_exists'] else 'MISSING'})")
        print(f"lib_path      {paths['lib_path']}  "
              f"({'found' if paths['lib_exists'] else 'MISSING'})")
    return paths


def doctor() -> int:
    """Report whether this machine can talk to Resolve. Returns an exit code."""
    print(f"resolve-ext {__version__}\n")
    print("--- Python ---")
    print(f"  {sys.version.split()[0]} at {sys.executable}")
    if sys.version_info < (3, 10):
        print("  ERROR: Python 3.10 or newer is required.")
        return 2
    print("  ok (3.10+)")

    print("\n--- DaVinci Resolve scripting API ---")
    paths = apply_resolve_env(verbose=True)
    problems = []
    if not paths["api_exists"]:
        problems.append(
            f"API folder not found at {paths['api_path']}.\n"
            "      DaVinci Resolve (Studio) must be installed, and external\n"
            "      scripting enabled: Preferences > System > General >\n"
            "      External scripting using > Local."
        )
    if not paths["lib_exists"]:
        problems.append(f"library not found at {paths['lib_path']}")
    if paths["api_exists"] and paths["modules_path"] and \
            not os.path.isdir(paths["modules_path"]):
        problems.append(f"Modules folder missing at {paths['modules_path']}")

    print("\n--- Import test ---")
    try:
        apply_resolve_env()
        import DaVinciResolveScript  # noqa: F401
        print("  ok: DaVinciResolveScript imports")
    except Exception as exc:
        problems.append(f"DaVinciResolveScript does not import: {exc}")
        print(f"  FAILED: {exc}")

    print("\n--- Live connection ---")
    try:
        app = _connect()
        if app:
            proj = app.GetProjectManager().GetCurrentProject()
            print(f"  ok: connected to Resolve; project = "
                  f"{proj.GetName() if proj else 'none open'}")
        else:
            problems.append(
                "Resolve is installed but not reachable. Start DaVinci Resolve "
                "Studio, and enable Preferences > System > General > "
                "External scripting using > Local."
            )
            print("  FAILED: no running Resolve instance answered")
    except Exception as exc:
        problems.append(f"connection failed: {exc}")
        print(f"  FAILED: {exc}")

    print("\n--- Result ---")
    if not problems:
        print("  All checks passed. This machine can run resolve-ext.")
        print("\n  Register it with your MCP client using the values from:")
        print("      resolve-ext env")
        return 0
    print(f"  {len(problems)} problem(s):")
    for i, p in enumerate(problems, 1):
        print(f"    {i}. {p}")
    return 1


def print_env() -> int:
    """Print the env block an MCP client needs, for this machine."""
    import json as _json
    import shutil as _shutil

    paths = find_resolve_paths()

    # Prefer the installed console script: it survives a Python upgrade and
    # does not hard-code a site-packages path. Fall back to the module path
    # when running from a checkout that was never installed.
    script = _shutil.which("resolve-ext")
    if script:
        command, args = script, []
        how = "installed console script"
    else:
        command, args = sys.executable, [os.path.abspath(__file__)]
        how = "running from source (pip install . gives you a cleaner command)"

    print(f"# resolve-ext {__version__} on {paths['platform']}")
    print(f"# entry point: {how}\n")

    env_block = {
        "RESOLVE_SCRIPT_API": paths["api_path"],
        "RESOLVE_SCRIPT_LIB": paths["lib_path"],
        "PYTHONPATH": paths["modules_path"],
    }
    # These are set automatically by the server when it can find the paths
    # itself — measured working with no environment at all. Pass them
    # explicitly only when Resolve lives somewhere non-standard.
    server = {"command": command}
    if args:
        server["args"] = args
    print("# Register the server (the env block is optional when Resolve is")
    print("# installed in its default location — the server finds it itself):")
    print(_json.dumps({"mcpServers": {"resolve-ext": server}}, indent=2))

    print("\n# With the env block made explicit:")
    server["env"] = env_block
    print(_json.dumps({"mcpServers": {"resolve-ext": server}}, indent=2))

    print("\n# Or with the Hermes CLI:")
    joined = " \\\n#      ".join(f'--env "{k}={v}"' for k, v in env_block.items())
    print("#    hermes mcp add resolve-ext \\")
    print(f"#      --command \"{command}\" \\")
    print(f"#      {joined} \\")
    if args:
        print(f"#      --args \"{args[0]}\"")
    else:
        print("#      --args \"\"   # the console script needs no argument")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point: run the server, or one of the helper commands."""
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in ("-h", "--help", "help"):
        print(__doc__)
        print("Commands:")
        print("  (none)     run the MCP server over stdio")
        print("  doctor     check this machine's Resolve setup")
        print("  env        print the env block an MCP client needs")
        print("  --version  print the version")
        return 0

    if args and args[0] in ("--version", "-V", "version"):
        print(f"resolve-ext {__version__}")
        return 0

    if args and args[0] == "doctor":
        return doctor()

    if args and args[0] == "env":
        return print_env()

    if args:
        print(f"resolve-ext: unknown command '{args[0]}'. Try --help.",
              file=sys.stderr)
        return 2

    # Default: be a stdio MCP server.
    apply_resolve_env()
    mcp.run()
    return 0


from mcp.server.fastmcp import FastMCP

# --- Resolve connection -------------------------------------------------

_RESOLVE = None


def _connect():
    """Return the Resolve app object, or None. Cached after first success."""
    global _RESOLVE
    if _RESOLVE is not None:
        return _RESOLVE
    try:
        import DaVinciResolveScript as dvr

        app = dvr.scriptapp("Resolve")
        if app:
            _RESOLVE = app
    except Exception:
        pass
    return _RESOLVE


def _err(msg: str) -> Dict[str, Any]:
    return {"error": msg}


def _ok(**kw) -> Dict[str, Any]:
    return {"success": True, **kw}


def _ctx():
    """Return (resolve, project_manager, project, timeline) or an error dict."""
    app = _connect()
    if not app:
        return None, _err(
            "Not connected to DaVinci Resolve. Start Resolve with "
            "Preferences > General > External scripting = Local."
        )
    pm = app.GetProjectManager()
    proj = pm.GetCurrentProject() if pm else None
    if not proj:
        return None, _err(
            "No project is open (Resolve is on the Project Manager). "
            "Open or create a project first — write operations silently fail otherwise."
        )
    tl = proj.GetCurrentTimeline()
    return (app, pm, proj, tl), None


def _find_item(tl, *, item_id: Optional[str] = None, track_type: str = "video",
               track_index: int = 1, name: Optional[str] = None):
    """Locate a TimelineItem by unique id or by name on a track."""
    if tl is None:
        return None, "No current timeline."
    items = tl.GetItemListInTrack(track_type, track_index) or []
    if item_id:
        for it in items:
            if it.GetUniqueId() == item_id:
                return it, None
        return None, f"No item with id '{item_id}' on {track_type} track {track_index}."
    if name:
        hits = [it for it in items if it.GetName() == name]
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return None, f"No item named '{name}' on {track_type} track {track_index}."
        return None, f"{len(hits)} items named '{name}' — pass item_id instead."
    return None, "Provide item_id or name."


def _find_clip_recursive(folder, clip_id: str):
    """Find a MediaPoolItem by unique id anywhere under `folder`.

    Walks recursively on purpose: ImportMedia drops a clip into the currently
    SELECTED bin, so a root-only lookup reports "not found" while the item
    exists one level down.
    """
    stack = [folder]
    while stack:
        f = stack.pop()
        for c in (f.GetClipList() or []):
            try:
                if c.GetUniqueId() == clip_id:
                    return c
            except Exception:
                continue
        stack.extend(f.GetSubFolderList() or [])
    return None


def _resolve_folder(mp, path: Optional[str] = None, folder_id: Optional[str] = None):
    """Resolve a folder by 'Master/Sub/Bin' path or by unique id."""
    root = mp.GetRootFolder()
    if folder_id:
        stack = [root]
        while stack:
            f = stack.pop()
            try:
                if f.GetUniqueId() == folder_id:
                    return f, None
            except Exception:
                pass
            stack.extend(f.GetSubFolderList() or [])
        return None, f"No folder with id '{folder_id}'."
    if path:
        segs = [s for s in str(path).split("/") if s]
        cur = root
        for seg in segs:
            nxt = None
            for sub in (cur.GetSubFolderList() or []):
                if sub.GetName() == seg:
                    nxt = sub
                    break
            if nxt is None:
                return None, f"Folder path '{path}' not found (missing '{seg}')."
            cur = nxt
        return cur, None
    return root, None


def _effect_info(eff) -> Dict[str, Any]:
    info = eff.GetInfo() or {}
    try:
        idx = eff.GetIndex()
    except Exception:
        idx = None
    try:
        enabled = eff.GetIsEnabled()
    except Exception:
        enabled = None
    return {
        "category": info.get("category"),
        "id": info.get("id"),
        "name": info.get("name"),
        "index": idx,
        "enabled": enabled,
    }


mcp = FastMCP("ResolveMCP-ext")


# --- camera comparison helpers -------------------------------------------

# The camera convention used across this project's Resolve work.
# Prefix -> (display name, marker colour). Prefixes are matched
# case-insensitively at the START of the clip name.
CAMERA_PREFIXES = {
    "ace": ("Insta360 AcePro", "Orange"),
    "go": ("Insta360 Go Ultra", "Green"),
    "luna": ("Insta360 Luna Ultra", "Cyan"),
    "x": ("Insta360 X5", "Blue"),
    "vid_": ("Handy", "Gray"),
}


def _camera_of(clip_name: str):
    """Map a clip name to (display_name, marker_colour) or (None, None).

    Matches the longest prefix first so 'luna...' is not caught by 'l', and
    'vid_' (an Android camera file like VID_20260614_170228.mp4) is checked
    before the single-letter 'x'.
    """
    name = (clip_name or "").lower()
    for prefix in sorted(CAMERA_PREFIXES, key=len, reverse=True):
        if name.startswith(prefix):
            return CAMERA_PREFIXES[prefix]
    return None, None


def _timeline_pixels(proj):
    """Timeline raster as (width, height) ints, defaulting to 1920x1080."""
    try:
        w = int(float(proj.GetSetting("timelineResolutionWidth") or 1920))
        h = int(float(proj.GetSetting("timelineResolutionHeight") or 1080))
    except Exception:
        return 1920, 1080
    return w, h


# 2x2 quadrant layout: name -> (x fraction of width, y fraction of height)
# +x is right, +y is UP (verified: Tilt 540 moves the image up on a 3840x2160
# timeline). Quadrant centres sit at +/- a quarter of each axis.
GRID_2X2 = {
    "ace": (-0.25, 0.25),    # top-left
    "go": (0.25, 0.25),      # top-right
    "luna": (-0.25, -0.25),  # bottom-left
    "x": (0.25, -0.25),      # bottom-right
}


def _call_any(candidates, method: str, *args):
    """Call `method` on the first candidate that answers usefully.

    Why so defensive: DaVinci Resolve hands out *dynamic proxy* objects, so
    `hasattr(obj, m)` and `callable(getattr(obj, m))` are TRUE for every method
    on every object — a Timeline reports the photo-album methods, Resolve
    reports Project's. Worse, calling a method the object does not own does not
    raise: it returns None.

    So the only reliable test is to call it and look at the result:
      - raises TypeError('NoneType' object is not callable) -> not this object
      - returns None while other candidates remain          -> keep looking
      - returns anything else (including 0 / [] / False)    -> this is it

    candidates: [(label, obj), ...]
    Returns (result, label, error).
    """
    last_err = None
    for label, obj in candidates:
        if obj is None:
            continue
        fn = getattr(obj, method, None)
        if fn is None:
            continue
        try:
            res = fn(*args)
        except TypeError as exc:
            if "not callable" in str(exc):
                last_err = f"{label}.{method}: not callable on this object"
                continue
            return None, label, f"{label}.{method}: {exc}"
        except Exception as exc:
            return None, label, f"{label}.{method}: {exc}"
        if res is None:
            last_err = f"{label}.{method} returned None"
            continue
        return res, label, None
    return None, None, last_err or f"No object exposes {method} on this build."


def _photo_objs(proj, mp):
    """Candidate objects for the project/media-pool level photo-album API.

    Measured on 21.1.2.10: the *listing* methods live on Project, the
    *creating/adding* ones on MediaPool, and Resolve answers none of them —
    but which is which is not documented and could move between builds, so both
    are tried in order by _call_any.
    """
    return [("MediaPool", mp), ("Project", proj)]


def _resolve_album(proj, mp, album_id=None, name=None):
    """Find a PhotoAlbum by unique id or name."""
    n, _, err = _call_any(_photo_objs(proj, mp), "GetPhotoAlbumCount")
    if err and n is None:
        return None, err
    albums = []
    for i in range(1, int(n or 0) + 1):
        a, _, _ = _call_any(_photo_objs(proj, mp), "GetPhotoAlbumByIndex", i)
        if a:
            albums.append(a)
    if album_id:
        for a in albums:
            if a.GetUniqueId() == album_id:
                return a, None
        return None, f"No photo album with id '{album_id}'."
    if name:
        hits = [a for a in albums if a.GetName() == name]
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return None, f"No photo album named '{name}'."
        return None, f"{len(hits)} albums named '{name}' — pass album_id."
    return None, "Provide album_id or name."



def _album_summary(a) -> Dict[str, Any]:
    try:
        n = len(a.GetPhotoList() or [])
    except Exception:
        n = None
    return {"name": a.GetName(), "id": a.GetUniqueId(), "photo_count": n}


@mcp.tool()
def effects(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Clip effects and effect properties on TimelineItems (Resolve 21.1.2+).

    The upstream server has no coverage for the 21.1.2 "Clip Effect Actions"
    and "Effect Properties" APIs. This tool exposes them.

    Actions:
      list_available(media_type?) -> {effects, count}
        — every effect Resolve can apply. media_type: 'video' (default),
          'photo' or 'audio'. Each entry: {category, id, name}.
          This is the lookup you need before apply().
          Example: find the id for a Fusion text+ via
          list_available(media_type="video").
      list_applied(item_id?|name?, track_type?, track_index?, category?)
        -> {effects, count}
        — effects currently ON a timeline item. category filters to
          'fusion' | 'ofx' | 'audio'; omit for all three.
      apply(item_id?|name?, category, id, track_type?, track_index?)
        -> {effect: {category,id,name,index,enabled}}
        — applies an effect to a timeline item. Get category+id from
          list_available().
      remove(item_id?|name?, indices?|category?, track_type?, track_index?)
        -> {removed: [...]}
        — removes effects from a timeline item. Either give explicit 1-based
          `indices` (with `category`), or `category` alone to remove every
          effect of that category.
      set_enabled(item_id?|name?, index, enabled, category?, track_type?,
                  track_index?) -> {success, effect}
        — toggle one effect on/off by its index.
      reorder(item_id?|name?, index, new_index, category?, track_type?,
              track_index?) -> {success, effects}
        — move an effect to another position in its category's stack.

    Addressing a timeline item: give `item_id` (GetUniqueId) — or `name`
    plus the track it sits on. Track defaults are video/1.
    """
    p = params or {}
    ctx, err = _ctx()
    if err:
        return err
    _, _, proj, tl = ctx

    if action == "list_available":
        media_type = p.get("media_type", "video")
        app = _connect()
        try:
            lst = app.GetEffectsList(media_type)
        except TypeError:
            lst = app.GetEffectsList()
        lst = lst or []
        out = [
            {
                "category": (e or {}).get("category"),
                "id": (e or {}).get("id"),
                "name": (e or {}).get("name"),
            }
            for e in lst
        ]
        return _ok(effects=out, count=len(out), media_type=media_type)

    if tl is None:
        return _err("No current timeline.")

    item, ierr = _find_item(
        tl,
        item_id=p.get("item_id"),
        track_type=p.get("track_type", "video"),
        track_index=int(p.get("track_index", 1)),
        name=p.get("name"),
    )
    if ierr:
        return ierr

    if action in ("list_applied", "apply", "remove", "set_enabled", "reorder"):
        pass
    else:
        return _err(
            f"Unknown action '{action}'. Use list_available, list_applied, "
            "apply, remove, set_enabled or reorder."
        )

    if action == "list_applied":
        cat = p.get("category")
        cats = [cat] if cat else ["fusion", "ofx", "audio"]
        found: List[Dict[str, Any]] = []
        for c in cats:
            try:
                for e in (item.GetEffects(c) or []):
                    found.append(_effect_info(e))
            except Exception as exc:
                found.append({"category": c, "error": str(exc)})
        return _ok(effects=found, count=len(found))

    if action == "apply":
        category = p.get("category")
        eid = p.get("id")
        if not category or not eid:
            return _err("apply needs category ('fusion'|'ofx'|'audio') and id.")
        eff = item.AddEffect(category, eid)
        if not eff:
            return _err(
                f"AddEffect returned None for category='{category}' id='{eid}'. "
                "Verify the id via effects(action='list_available')."
            )
        return _ok(effect=_effect_info(eff))

    if action == "remove":
        cat = p.get("category")
        idxs = p.get("indices")
        if not cat:
            return _err("remove needs category ('fusion'|'ofx'|'audio').")
        current = item.GetEffects(cat) or []
        targets = []
        if idxs:
            by_index = {}
            for e in current:
                try:
                    by_index[e.GetIndex()] = e
                except Exception:
                    pass
            for i in idxs:
                if i in by_index:
                    targets.append(by_index[i])
            if not targets:
                return _err(f"No effects at indices {idxs} in category '{cat}'.")
        else:
            targets = list(current)
        if not targets:
            return _ok(removed=[], note=f"No '{cat}' effects to remove.")
        res = item.DeleteEffects(targets)
        if not res:
            return _err("DeleteEffects returned False.")
        remaining = []
        for e in (item.GetEffects(cat) or []):
            remaining.append(_effect_info(e))
        return _ok(removed_estimated=len(targets), remaining=remaining)

    if action == "set_enabled":
        cat = p.get("category")
        index = p.get("index")
        enabled = p.get("enabled")
        if index is None or enabled is None:
            return _err("set_enabled needs index and enabled.")
        cats = [cat] if cat else ["fusion", "ofx", "audio"]
        for c in cats:
            for e in (item.GetEffects(c) or []):
                try:
                    if e.GetIndex() == index:
                        if not e.SetIsEnabled(bool(enabled)):
                            return _err(f"SetIsEnabled returned False on {c} #{index}.")
                        return _ok(effect=_effect_info(e))
                except Exception:
                    continue
        return _err(f"No effect with index {index}" + (f" in '{cat}'." if cat else "."))

    if action == "reorder":
        cat = p.get("category")
        index = p.get("index")
        new_index = p.get("new_index")
        if index is None or new_index is None:
            return _err("reorder needs index and new_index.")
        cats = [cat] if cat else ["fusion", "ofx", "audio"]
        for c in cats:
            for e in (item.GetEffects(c) or []):
                try:
                    if e.GetIndex() == index:
                        if not e.SetIndex(int(new_index)):
                            return _err(f"SetIndex returned False on {c} #{index}.")
                        out = []
                        for e2 in (item.GetEffects(c) or []):
                            out.append(_effect_info(e2))
                        return _ok(effects=out)
                except Exception:
                    continue
        return _err(f"No effect with index {index}" + (f" in '{cat}'." if cat else "."))

    return _err(f"Unhandled action '{action}'.")


@mcp.tool()
def clip_attrs(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Copy clip attributes between timeline items (Resolve 21.1.2+).

    `TimelineItem.CopyAttributes` is the API behind Edit-page Paste Attributes.
    It is what makes a per-camera look repeatable: grade one clip, then push
    the same attributes onto every other clip of that camera.

    Actions:
      options() -> {groups}
        — the full option vocabulary, grouped, from Resolve's own type stubs.
      copy(source_id?, source_name?, target_ids?, target_names?, options,
           copy_all_video?, copy_all_audio?, track_type?, track_index?)
        -> {success, copied_to, options_used}
        — copy attributes from one source item onto one or more targets.
          `options` is a dict of the flags from options(); a true value means
          copy that attribute. Shorthands:
            copy_all_video=true -> allVideoAttributes
            copy_all_audio=true -> allAudioAttributes
          Common per-camera case:
            {"colorCorrection": true, "allZoomAttributes": true,
             "allCropAttributes": true, "videoPlugins": true}
      read(item_id?|name?, track_type?, track_index?) -> {attributes}
        — the readable video attributes of an item (position, zoom, crop,
          opacity, rotation, composition mode), so you can see what a copy
          would carry.

    Notes:
      - Targets are addressed by `target_ids` (GetUniqueId list) or
        `target_names` (exact names on one track). Pick one form.
      - CopyAttributes needs the source and targets on the SAME timeline.
    """
    p = params or {}
    ctx, err = _ctx()
    if err:
        return err
    _, _, proj, tl = ctx

    OPTION_GROUPS = {
        "clip": ["allClipAttributes", "clipColor", "flags", "markers"],
        "video": [
            "allVideoAttributes", "compositionMode", "opacity", "position",
            "rotationAngle", "anchorPoint", "pitch", "yaw",
        ],
        "zoom_crop_flip": [
            "allZoomAttributes", "scaleX", "scaleY",
            "allCropAttributes", "cropLeft", "cropRight", "cropTop",
            "cropBottom", "cropSoftness", "retainImagePosition",
            "allFlipAttributes", "flipV", "flipH",
        ],
        "retime": ["retimeProcess", "motionEstimation", "retimeEffect", "rippleSequence"],
        "grade_fusion": ["colorCorrection", "fusionEffects", "videoPlugins"],
        "audio": ["allAudioAttributes", "audioVolume", "audioPlugins", "audioEqualizer"],
    }

    if action == "options":
        flat = sorted({o for v in OPTION_GROUPS.values() for o in v})
        return _ok(groups=OPTION_GROUPS, all_options=flat, count=len(flat))

    if tl is None:
        return _err("No current timeline.")

    track_type = p.get("track_type", "video")
    track_index = int(p.get("track_index", 1))

    if action == "read":
        item, ierr = _find_item(
            tl, item_id=p.get("item_id"), track_type=track_type,
            track_index=track_index, name=p.get("name"),
        )
        if ierr:
            return ierr
        keys = [
            "ZoomX", "ZoomY", "ZoomGang", "RotationAngle",
            "AnchorPointX", "AnchorPointY", "Opacity", "CompositeMode",
            "CropLeft", "CropRight", "CropTop", "CropBottom", "CropSoftness",
            "FlipX", "FlipY", "Pan", "Tilt",
        ]
        attrs = {}
        for k in keys:
            try:
                attrs[k] = item.GetProperty(k)
            except Exception:
                pass
        return _ok(
            name=item.GetName(),
            attributes=attrs,
            note=(
                "GetProperty('Position') returns a bool on 21.1.2 — the position "
                "is carried by 'Pan'/'Tilt' (x/y in pixels). Rotation is in "
                "degrees; crop values are 0..1; Zoom is a multiplier."
            ),
        )

    if action != "copy":
        return _err(f"Unknown action '{action}'. Use options, copy or read.")

    src, serr = _find_item(
        tl, item_id=p.get("source_id"), track_type=track_type,
        track_index=track_index, name=p.get("source_name"),
    )
    if serr:
        return _err(f"Source: {serr}")

    opts = dict(p.get("options") or {})
    if p.get("copy_all_video"):
        opts["allVideoAttributes"] = True
    if p.get("copy_all_audio"):
        opts["allAudioAttributes"] = True
    if not opts:
        return _err(
            "No options given. Pass `options` (see clip_attrs(action='options')), "
            "or copy_all_video=true / copy_all_audio=true."
        )
    unknown = [k for k in opts if k not in {o for v in OPTION_GROUPS.values() for o in v}]
    if unknown:
        return _err(f"Unknown option(s): {unknown}. See clip_attrs(action='options').")

    targets: List[Any] = []
    missing: List[str] = []
    tids = p.get("target_ids")
    tnames = p.get("target_names")
    if tids:
        by_id = {}
        for it in (tl.GetItemListInTrack(track_type, track_index) or []):
            by_id[it.GetUniqueId()] = it
        for i in tids:
            if i in by_id:
                targets.append(by_id[i])
            else:
                missing.append(i)
    elif tnames:
        by_name: Dict[str, List[Any]] = {}
        for it in (tl.GetItemListInTrack(track_type, track_index) or []):
            by_name.setdefault(it.GetName(), []).append(it)
        for n in tnames:
            hits = by_name.get(n, [])
            if len(hits) == 1:
                targets.append(hits[0])
            elif hits:
                missing.append(f"{n} (ambiguous: {len(hits)} matches)")
            else:
                missing.append(n)
    else:
        return _err("Pass target_ids or target_names.")

    if not targets:
        return _err(f"No targets resolved. Missing: {missing}")

    res = src.CopyAttributes(targets, opts)
    if res is False:
        return _err(
            "CopyAttributes returned False. Source and targets must be on the "
            "same timeline and the option keys must be valid."
        )
    return _ok(
        copied_to=[t.GetName() for t in targets],
        count=len(targets),
        options_used=opts,
        unresolved=missing,
    )


@mcp.tool()
def resolve_ext_status() -> Dict[str, Any]:
    """Health check for the resolve-ext server and its Resolve connection.

    Reports whether Resolve is reachable, which product/version is live,
    whether a project is open, and which of this server's surfaces are
    usable on that build.
    """
    app = _connect()
    if not app:
        return _err(
            "Not connected to DaVinci Resolve. Start Resolve with "
            "Preferences > General > External scripting = Local, then retry."
        )
    out: Dict[str, Any] = {"connected": True}
    try:
        out["product"] = app.GetProductName()
        out["version"] = app.GetVersionString()
        out["is_studio"] = bool(app.IsStudio())
    except Exception as exc:
        out["version_error"] = str(exc)
    pm = app.GetProjectManager()
    proj = pm.GetCurrentProject() if pm else None
    out["project"] = proj.GetName() if proj else None
    tl = proj.GetCurrentTimeline() if proj else None
    out["timeline"] = tl.GetName() if tl else None

    # hasattr() is worthless on Resolve proxies: every method name answers True
    # on every object (see "The Proxy Trap" in the README). Probe by calling and
    # looking at the result, which is the only reliable test.
    probes: Dict[str, Any] = {}
    probes["Resolve.GetEffectsList"] = _call_any([("Resolve", app)], "GetEffectsList")[0] is not None
    if tl:
        items = _call_any([("Timeline", tl)], "GetItemListInTrack", "video", 1)[0]
        probes["Timeline.GetItemListInTrack"] = isinstance(items, list)
        if isinstance(items, list) and items:
            it = items[0]
            probes["TimelineItem.GetProperty"] = (
                _call_any([("TimelineItem", it)], "GetProperty", "ZoomX")[0] is not None
            )
            probes["TimelineItem.GetFusionCompCount"] = (
                _call_any([("TimelineItem", it)], "GetFusionCompCount")[0] is not None
            )
    else:
        probes["Timeline.GetItemListInTrack"] = None
    out["surfaces"] = probes
    return _ok(**out)


@mcp.tool()
def clip_position(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Inspect clip placement, handle offsets, gaps and timeline enable state.

    **SetPosition / MoveItems are BROKEN on Resolve 21.1.2.10** — measured to
    return False for every input (real clips and stills, int and float
    startFrame, even a no-op), while other write APIs work in the same
    session. `set` and `move` therefore report an honest error rather than
    pretending to have moved anything. Use `get` to plan, and reposition in
    the Edit page by hand.

    Actions that DO work:
      get(item_id?|name?, track_type?, track_index?) -> {position, left_offset,
                                                         right_offset, start, end}
        — where an item sits and how many frames of handle it offers. This is
          the read you need before deciding a trim. READ-ONLY, safe.
      enabled() -> {enabled}
        — read the timeline's enabled state. Setting it (enabled=true/false)
          works but turns the timeline non-current, so later calls report
          'No current timeline' until it is switched back in the GUI.

    Actions DISABLED or exposing a broken API on this build:
      set(start_frame?|new_track_index?) — SetPosition returns False for every
        input, including no-ops.
      move(items=[…]) — same broken call per item.
      set_offset(left?|right?) — SetLeftOffset does NOT nudge the edit point:
        it EXTENDS the clip from source media. Measured: a clip at frame 400
        with duration 120 became start=-85995, duration=86515 after
        SetLeftOffset(5), and could not be restored by setting 0.
      delete_gaps() — closes the gaps between clips so they sit back to back.
        **Verified working** on a timeline whose StartFrame/EndFrame agree with
        its contents. It appeared to be a silent no-op in an earlier release;
        that measurement ran on a timeline whose metadata contradicted its
        contents (StartFrame == EndFrame while holding three clips). The action
        compares the clip starts before and after and reports the real outcome
        either way.

    Addressing: `item_id` (GetUniqueId) or `name` on a track. Track defaults
    video/1. Frame numbers are absolute timeline frames, not timecode.
    """
    p = params or {}
    ctx, err = _ctx()
    if err:
        return err
    _, _, proj, tl = ctx
    if tl is None:
        return _err("No current timeline.")

    track_type = p.get("track_type", "video")
    track_index = int(p.get("track_index", 1))

    def _resolve():
        return _find_item(
            tl, item_id=p.get("item_id"), track_type=track_type,
            track_index=track_index, name=p.get("name"),
        )

    if action == "get":
        item, ierr = _resolve()
        if ierr:
            return ierr
        pos = None
        try:
            pos = item.GetPosition()
        except Exception as exc:
            pos = {"error": str(exc)}
        lo = ro = None
        try:
            lo = item.GetLeftOffset()
            ro = item.GetRightOffset()
        except Exception:
            pass
        return _ok(
            name=item.GetName(),
            position=pos,
            left_offset=lo,
            right_offset=ro,
            start=item.GetStart(),
            end=item.GetEnd(),
            duration=item.GetDuration(),
            note=(
                "left/right_offset = frames of handle available on that edit "
                "point. position = {trackType, trackIndex, startFrame}."
            ),
        )

    if action == "set":
        item, ierr = _resolve()
        if ierr:
            return ierr
        pos: Dict[str, Any] = {}
        if p.get("start_frame") is not None:
            pos["startFrame"] = float(p["start_frame"])
        if p.get("new_track_index") is not None:
            pos["trackIndex"] = int(p["new_track_index"])
        if not pos:
            return _err("set needs start_frame and/or new_track_index.")
        ok = item.SetPosition(pos, bool(p.get("move_linked", True)))
        if not ok:
            return _err(
                "SetPosition returned False. MEASURED on DaVinci Resolve "
                "21.1.2.10: this call fails for EVERY input tried — real video "
                "clips and stills, integer and float startFrame, a no-op "
                "startFrame equal to the current one, and both moveLinkedItems "
                "values. Timeline.MoveItems fails identically, while other "
                "write APIs (SetCurrentTimecode) succeed in the same session. "
                "Treat SetPosition/MoveItems as BROKEN on this build and "
                "reposition clips in the Edit page by hand. Nothing was moved."
            )
        return _ok(name=item.GetName(), position=item.GetPosition())

    if action == "move":
        spec = p.get("items")
        if not spec or not isinstance(spec, list):
            return _err("move needs items=[{item_id|name, track_index?, start_frame?}, …].")
        pool = tl.GetItemListInTrack(track_type, track_index) or []
        by_id = {it.GetUniqueId(): it for it in pool}
        by_name: Dict[str, List[Any]] = {}
        for it in pool:
            by_name.setdefault(it.GetName(), []).append(it)
        targets: List[Any] = []
        for s in spec:
            it = None
            if s.get("item_id"):
                it = by_id.get(s["item_id"])
            elif s.get("name"):
                hits = by_name.get(s["name"], [])
                it = hits[0] if len(hits) == 1 else None
            if it is None:
                return _err(f"Could not resolve item spec {s} on {track_type} track {track_index}.")
            targets.append(it)
        # NOTE: Timeline.MoveItems is broken on 21.1.2.10 (measured: always
        # False). This applies the per-item moves with SetPosition, which is
        # equally broken — the honest outcome is a per-item failure report
        # rather than a silent no-op.
        results = []
        for s, it in zip(spec, targets):
            if s.get("start_frame") is None and s.get("track_index") is None:
                results.append({"name": it.GetName(), "skipped": "no target given"})
                continue
            pos: Dict[str, Any] = {}
            if s.get("start_frame") is not None:
                pos["startFrame"] = float(s["start_frame"])
            if s.get("track_index") is not None:
                pos["trackIndex"] = int(s["track_index"])
            ok = it.SetPosition(pos, bool(p.get("move_linked", True)))
            results.append({
                "name": it.GetName(),
                "success": bool(ok),
                "position": it.GetPosition() if ok else None,
            })
        if results and all(not r.get("success") for r in results if "success" in r):
            return _err(
                "Every SetPosition call returned False. MEASURED on Resolve "
                "21.1.2.10: SetPosition and Timeline.MoveItems are BROKEN on "
                "this build (they fail for every input, including no-ops), "
                "while other write APIs work. Reposition in the Edit page."
            )
        return _ok(results=results)

    if action == "set_offset":
        return _err(
            "set_offset is DISABLED. MEASURED on Resolve 21.1.2.10: "
            "SetLeftOffset(5) on a clip starting at frame 400 moved it to "
            "-85995 and inflated its duration from 120 to 86515 frames — it "
            "extends the clip using the source media, it does NOT nudge the "
            "edit point. Setting the offset back to 0 did not restore the "
            "original position (the clip stayed at -86000). This is "
            "destructive and not reversible through the API, so it is not "
            "exposed. Read offsets with action='get' (read-only is safe); "
            "make trims with the usual Resolve edit tools."
        )

    if action == "delete_gaps":
        if tl is None:
            return _err(
                "No current timeline. If you previously set enabled=false, the "
                "timeline is no longer current — re-enable it in the GUI."
            )
        before = [(i.GetName(), i.GetStart()) for i in (tl.GetItemListInTrack(track_type, track_index) or [])]
        try:
            ok = tl.DeleteGaps()
        except Exception as exc:
            return _err(f"DeleteGaps raised: {exc}")
        after = [(i.GetName(), i.GetStart()) for i in (tl.GetItemListInTrack(track_type, track_index) or [])]
        changed = before != after
        if not changed:
            # Corrected: DeleteGaps is NOT a silent no-op. It works, but it
            # does nothing on a timeline whose metadata contradicts its
            # contents - which is what happens when AppendToTimeline is fed
            # absolute recordFrame values below StartFrame.
            return _err(
                f"DeleteGaps returned {ok!r} but nothing moved — the items still "
                f"start at {[s for _, s in after]}. On this build that happens "
                "when the timeline's metadata contradicts its contents: a "
                "timeline built with AppendToTimeline using absolute recordFrame "
                "values below StartFrame reports StartFrame == EndFrame (duration "
                "0) while still holding clips, and SetLeftOffset/DeleteGaps then "
                "have nothing valid to act on. Check GetStartFrame()/GetEndFrame() "
                "and rebuild the timeline with recordFrame >= the start frame. "
                "Nothing was changed by this call."
            )
        return _ok(deleted=True, items_before=len(before), items_after=len(after),
                   starts_before=[s for _, s in before], starts_after=[s for _, s in after])

    if action == "enabled":
        if p.get("enabled") is None:
            return _ok(enabled=tl.GetIsEnabled())
        ok = tl.SetIsEnabled(bool(p["enabled"]))
        if not ok:
            return _err("SetIsEnabled returned False.")
        state = None
        try:
            state = tl.GetIsEnabled()
        except Exception:
            pass
        return _ok(
            enabled=state,
            note=(
                "Turning the timeline off clears GetCurrentTimeline(), so later "
                "calls will report 'No current timeline' until it is re-enabled "
                "in the GUI. This is a Resolve behaviour, not an error here."
            ) if state is False else None,
        )

    if action == "move_items":
        return _err("Use action='move' instead; 'move_items' was renamed.")

    return _err(
        f"Unknown action '{action}'. Use get, set, move, set_offset, "
        "delete_gaps or enabled."
    )


@mcp.tool()
def export_frame(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Export a frame as a still — from a timeline, a clip, or the media pool.

    Resolve 21.1.2 added ExportFrame on Timeline, TimelineItem and
    MediaPoolItem. The upstream server's frame capture goes through a render
    or a Gallery still; this is the direct call.

    Actions:
      item(item_id?|name?, frame_offset?, output_type?, file_path?, format?,
           max_dimension?, track_type?, track_index?)
        — TimelineItem.ExportFrame. **This is the one that works.** Offset is
          0-based from the ITEM start and must be < the item's duration
          (verified: 0..119 succeed on a 120-frame item, 120+ is refused).
      media(clip_id, frame_offset?, output_type?, file_path?, format?,
            max_dimension?)
        — MediaPoolItem.ExportFrame. Also verified working; offset is 0-based
          from the SOURCE start, ignoring the timeline.
      timeline(frame_offset, …)
        — Timeline.ExportFrame. Offset is **0-based from the TIMELINE start**
          (`StartFrame`), valid `0 .. (EndFrame - StartFrame - 1)`.
          Verified on 21.1.2.10 against a 480-frame timeline: offsets 0..479
          succeed, 480 is refused with 'frameOffset is out of range'.
          An absolute frame (e.g. the value from `GetStartFrame()`) is ALWAYS
          refused, which reads like a failure but is correct behaviour. An
          earlier release documented that rejection as a defect; that was a
          wrong measurement on an empty timeline, corrected here.

    Parameters:
      output_type  'file' (needs file_path) or 'encodedString' (default).
      file_path    Output path; format is inferred from the extension.
      format       'jpg' (default) or 'png' — only for output_type
                   'encodedString'.
      max_dimension  Cap the longer edge in pixels (default 0 = full size).

    Returns for output_type='file': {success, path, bytes}.
    Returns for 'encodedString': {saved_to} — the base64 is decoded and
    written to <server dir>/out/, with only a short prefix returned inline.
    """
    import base64

    p = params or {}
    ctx, err = _ctx()
    if err:
        return err
    app, _, proj, tl = ctx

    out_type = p.get("output_type", "encodedString")
    opts: Dict[str, Any] = {"outputType": out_type}
    if out_type == "file":
        if not p.get("file_path"):
            return _err("output_type='file' needs file_path.")
        opts["filePath"] = p["file_path"]
    else:
        opts["encodedImageFormat"] = p.get("format", "jpg")
    if p.get("max_dimension"):
        opts["maxDimension"] = int(p["max_dimension"])

    def _wrap(res, label):
        res = res or {}
        if not res.get("success"):
            return _err(f"{label}: {res.get('error') or 'ExportFrame reported no success.'}")
        out: Dict[str, Any] = {"success": True, "target": label}
        if out_type == "file":
            out["path"] = p.get("file_path")
            try:
                out["bytes"] = os.path.getsize(p["file_path"])
            except Exception:
                out["bytes"] = None
        else:
            data = res.get("data") or ""
            out["format"] = p.get("format", "jpg")
            out["base64_length"] = len(data)
            out["base64_prefix"] = data[:80]
            try:
                raw = base64.b64decode(data)
                ext = "png" if p.get("format", "jpg") == "png" else "jpg"
                outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
                os.makedirs(outdir, exist_ok=True)
                dest = os.path.join(outdir, f"frame_{abs(hash(data)) % 10**10}.{ext}")
                with open(dest, "wb") as fh:
                    fh.write(raw)
                out["saved_to"] = dest
                out["bytes"] = len(raw)
            except Exception as exc:
                out["save_error"] = str(exc)
        return _ok(**out)

    if action == "timeline":
        if tl is None:
            return _err("No current timeline.")
        off = int(p.get("frame_offset", 0))
        res = tl.ExportFrame(off, opts) or {}
        if not res.get("success"):
            # The offset is RELATIVE to the timeline start, which is the single
            # most common way to get this wrong (passing GetStartFrame()).
            # An earlier release reported the resulting rejection as a defect;
            # it is correct behaviour, so explain it instead.
            sf, ef = tl.GetStartFrame(), tl.GetEndFrame()
            dur = (ef - sf) if (sf is not None and ef is not None) else None
            if sf is not None and off >= sf:
                hint = (
                    f" The offset looks ABSOLUTE: {off} was passed while the "
                    f"timeline starts at frame {sf}. Use an offset RELATIVE to "
                    f"the timeline start — {off - sf} would be the same frame."
                )
            elif dur is not None and off >= dur:
                hint = (f" The offset must be below the timeline duration "
                        f"({dur} frames): valid range is 0..{dur - 1}.")
            elif dur is not None:
                hint = f" Valid range on this timeline is 0..{dur - 1}."
            else:
                hint = ""
            return _err(
                f"Timeline.ExportFrame(frameOffset={off}) failed: "
                f"{res.get('error')}.{hint}"
            )
        return _wrap(res, f"timeline frame_offset={off}")

    if action == "item":
        if tl is None:
            return _err("No current timeline.")
        item, ierr = _find_item(
            tl, item_id=p.get("item_id"),
            track_type=p.get("track_type", "video"),
            track_index=int(p.get("track_index", 1)),
            name=p.get("name"),
        )
        if ierr:
            return ierr
        off = int(p.get("frame_offset", 0))
        return _wrap(item.ExportFrame(off, opts), f"item '{item.GetName()}' offset={off}")

    if action == "media":
        cid = p.get("clip_id")
        if not cid:
            return _err("media needs clip_id.")
        mp = proj.GetMediaPool()
        found = _find_clip_recursive(mp.GetRootFolder(), cid)
        if not found:
            return _err(f"No media pool clip with id '{cid}'.")
        off = int(p.get("frame_offset", 0))
        return _wrap(found.ExportFrame(off, opts), f"media '{found.GetName()}' offset={off}")

    return _err(f"Unknown action '{action}'. Use timeline, item or media.")


@mcp.tool()
def folder_ops(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Folder hierarchy lookups the upstream server does not expose.

    Actions:
      parent_of_clip(clip_id) -> {name, id, path}
        — which bin a media pool clip lives in (MediaPoolItem.GetParentFolder).
      parent_of_folder(path?|folder_id?) -> {name, id, path} | {root: true}
        — a folder's parent (Folder.GetParentFolder). The root folder has none.
      path(clip_id?|folder_id?) -> {path, segments}
        — the full "Master/Sub/Bin" path of a clip or folder.
      find_clip(clip_id) -> {name, folder_path}
        — locate a clip by id anywhere in the tree.
    """
    p = params or {}
    ctx, err = _ctx()
    if err:
        return err
    _, _, proj, _ = ctx
    mp = proj.GetMediaPool()

    def _path_of_folder(folder, root):
        segs = []
        cur = folder
        seen = 0
        while cur is not None and seen < 64:
            seen += 1
            if cur.GetUniqueId() == root.GetUniqueId():
                break
            segs.append(cur.GetName())
            try:
                cur = cur.GetParentFolder()
            except Exception:
                cur = None
        segs.reverse()
        return "/".join([root.GetName()] + segs) if segs else root.GetName()

    root = mp.GetRootFolder()

    if action in ("parent_of_clip", "find_clip"):
        cid = p.get("clip_id")
        if not cid:
            return _err(f"{action} needs clip_id.")
        found = None
        stack = [root]
        while stack:
            f = stack.pop()
            for c in (f.GetClipList() or []):
                if c.GetUniqueId() == cid:
                    found = (c, f)
                    break
            if found:
                break
            stack.extend(f.GetSubFolderList() or [])
        if not found:
            return _err(f"No clip with id '{cid}'.")
        clip, folder = found
        if action == "find_clip":
            return _ok(name=clip.GetName(), folder_path=_path_of_folder(folder, root))
        return _ok(
            name=clip.GetName(),
            folder=folder.GetName(),
            folder_id=folder.GetUniqueId(),
            path=_path_of_folder(folder, root),
        )

    if action in ("parent_of_folder", "path"):
        f = root
        if p.get("folder_id") or p.get("path"):
            f, ferr = _resolve_folder(mp, p.get("path"), p.get("folder_id"))
            if ferr:
                return ferr
        if action == "path":
            from_path = _path_of_folder(f, root)
            return _ok(path=from_path, segments=from_path.split("/"))
        if f.GetUniqueId() == root.GetUniqueId():
            return _ok(root=True, name=root.GetName())
        try:
            par = f.GetParentFolder()
        except Exception:
            par = None
        if par is None:
            return _ok(root=True, name=f.GetName())
        return _ok(
            name=par.GetName(),
            id=par.GetUniqueId(),
            path=_path_of_folder(par, root),
        )

    return _err(f"Unknown action '{action}'. Use parent_of_clip, parent_of_folder, path or find_clip.")


@mcp.tool()
def photo_albums(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Photo albums and their items (Resolve 21.1.2+).

    A photo album is the stills/photo counterpart of a timeline: an ordered set
    of photo items, each with its own grade, flags, rating and versions.
    Measured on 21.1.2.10 this whole area works — 9/9 PhotoAlbum methods and
    20/20 PhotoAlbumItem methods answered.

    The API is split across objects and the split is NOT documented: the album
    *listing* methods live on Project, while creating/adding lives on MediaPool,
    and Resolve itself answers none of them. This tool resolves the right object
    at call time, so it keeps working if a build moves them.

    Albums:
      list() -> {albums, count}
      current() -> {album|None}
      set_current(album_id?|name?) -> {success, album}
      create(name) -> {album}
      create_from_photos(name, clip_ids) -> {album}
        — THE RELIABLE WAY to get photos into an album: VERIFIED working
          (added 2 photos, read back). Prefer this over add_photos.
      delete(album_ids?) -> {success, deleted}
      rename(album_id?|name?, new_name) -> {success, album}
      quick_export_presets() -> {presets}
      render_settings(settings?) -> {settings}

    Photos inside an album:
      photos(album_id?|name?) -> {photos, count}
      add_photos(clip_ids, album_id?|name?) -> {added, count}
        — BROKEN on 21.1.2.10: AddToPhotoAlbum adds nothing and returns an
          empty list. This action verifies by reading the album back and
          reports the failure with the measurement instead of a false success.
          Use create_from_photos instead (verified working).
      remove_photos(photo_ids, album_id?|name?) -> {success, remaining}
      current_item(album_id?|name?) -> {photo|None}

    Per-photo properties (address a photo by photo_id, or by name inside an
    album):
      photo(photo_id|photo_name?, album_id?|name?) -> {photo}
      rate(photo_id|photo_name?, stars) -> {success, rating}
      flag(photo_id|photo_name?, color?|clear?) -> {success, flags}
      clip_color(photo_id|photo_name?, color?|clear?) -> {success, clip_color}
      versions(photo_id|photo_name?) -> {versions, current}
      add_version(photo_id|photo_name?, version_name) -> {success, versions}
      load_version(photo_id|photo_name?, version_name) -> {success}
      delete_version(photo_id|photo_name?, version_name) -> {success}
      copy_grade(source_photo_id|source_photo_name?, photo_ids) -> {success}
      effects_list(photo_id|photo_name?) -> {effects, count}
      effect_apply(photo_id|photo_name?, category, id) -> {effect}
      effect_remove(photo_id|photo_name?, category, indices?) -> {success}
      fusion_comps(photo_id|photo_name?) -> {comps, count}
      fusion_add(photo_id|photo_name?) -> {success, comps}
      stills(album_id?|name?, all_photos?) -> {success, grabbed}

    Notes:
      - `clip_ids` are MediaPoolItem ids (see media_pool_item.get_name).
      - Ratings are 0-5; the API silently accepts out-of-range values, so this
        tool clamps and reports what actually came back.

    Measured on Resolve 21.1.2.10:
      WORKING  — 9/9 PhotoAlbum methods, 20/20 PhotoAlbumItem methods,
                 CreatePhotoAlbumFromPhotos (photos land and read back),
                 ratings/flags/versions persist, AddFusionComp on a photo.
      BROKEN   — AddToPhotoAlbum adds nothing (four variants tried);
                 Graph.ResetAllNodeColors exists on photo graphs but not on
                 timeline clip graphs; MediaPoolItem.GetNodeGraph not callable;
                 a freshly created album is not automatically "current"
                 (this tool sets it).
    """
    p = params or {}
    ctx, err = _ctx()
    if err:
        return err
    _, _, proj, _ = ctx
    mp = proj.GetMediaPool()

    # ---- album listing / lifecycle -------------------------------------
    if action == "list":
        n, _who, err = _call_any(_photo_objs(proj, mp), "GetPhotoAlbumCount")
        if err and n is None:
            return _err(err)
        out = []
        for i in range(1, int(n or 0) + 1):
            a, _w, _e = _call_any(_photo_objs(proj, mp), "GetPhotoAlbumByIndex", i)
            if a:
                out.append(_album_summary(a))
        return _ok(albums=out, count=len(out))

    if action == "current":
        a, _who, err = _call_any(_photo_objs(proj, mp), "GetCurrentPhotoAlbum")
        if err and a is None and "returned None" not in (err or ""):
            return _err(err)
        return _ok(album=_album_summary(a) if a else None)

    if action == "set_current":
        album, aerr = _resolve_album(proj, mp, p.get("album_id"), p.get("name"))
        if aerr:
            return aerr
        _r, _who, err = _call_any(_photo_objs(proj, mp), "SetCurrentPhotoAlbum", album)
        if err or _r is None:
            return _err(err or "SetCurrentPhotoAlbum returned nothing.")
        if _r is False:
            return _err("SetCurrentPhotoAlbum returned False.")
        return _ok(album=_album_summary(album))

    if action == "create":
        name = p.get("name")
        if not name:
            return _err("create needs name.")
        a, _who, err = _call_any(_photo_objs(proj, mp), "CreateEmptyPhotoAlbum", name)
        if err or not a:
            return _err(err or f"CreateEmptyPhotoAlbum('{name}') returned nothing.")
        # A freshly created album is not automatically current, and
        # AddToPhotoAlbum appends to the CURRENT album — so set it here.
        _call_any(_photo_objs(proj, mp), "SetCurrentPhotoAlbum", a)
        return _ok(album=_album_summary(a))

    if action == "create_from_photos":
        name, ids = p.get("name"), p.get("clip_ids")
        if not name or not ids:
            return _err("create_from_photos needs name and clip_ids.")
        items = []
        root = mp.GetRootFolder()
        for cid in ids:
            c = _find_clip_recursive(root, cid)
            if not c:
                return _err(f"No media pool clip with id '{cid}'.")
            items.append(c)
        a, _who, err = _call_any(_photo_objs(proj, mp), "CreatePhotoAlbumFromPhotos", name, items)
        if err or not a:
            return _err(err or "CreatePhotoAlbumFromPhotos returned nothing.")
        _call_any(_photo_objs(proj, mp), "SetCurrentPhotoAlbum", a)
        return _ok(album=_album_summary(a))

    if action == "delete":
        ids = p.get("album_ids")
        if ids:
            targets = []
            for aid in ids:
                a, e = _resolve_album(proj, mp, album_id=aid)
                if e:
                    return e
                targets.append(a)
        else:
            n, _w, _e = _call_any(_photo_objs(proj, mp), "GetPhotoAlbumCount")
            targets = []
            for i in range(1, int(n or 0) + 1):
                a, _w2, _e2 = _call_any(_photo_objs(proj, mp), "GetPhotoAlbumByIndex", i)
                if a:
                    targets.append(a)
        if not targets:
            return _ok(deleted=0, note="No albums to delete.")
        names = [t.GetName() for t in targets]
        ok, _who, err = _call_any(_photo_objs(proj, mp), "DeletePhotoAlbums", targets)
        if err or ok is None:
            return _err(err or "DeletePhotoAlbums returned nothing.")
        if ok is False:
            return _err("DeletePhotoAlbums returned False.")
        return _ok(deleted=len(targets), names=names)

    if action == "rename":
        album, aerr = _resolve_album(proj, mp, p.get("album_id"), p.get("name"))
        if aerr:
            return aerr
        new_name = p.get("new_name")
        if not new_name:
            return _err("rename needs new_name.")
        ok = album.SetName(new_name)
        if not ok:
            return _err(
                f"SetName('{new_name}') returned False — the name must be "
                "unique among albums in the project."
            )
        return _ok(album=_album_summary(album))

    if action == "quick_export_presets":
        res, _who, err = _call_any(_photo_objs(proj, mp), "GetPhotoQuickExportRenderPresets")
        if err and res is None:
            return _err(err)
        return _ok(presets=res or [])

    if action == "render_settings":
        settings = p.get("settings")
        if settings is None:
            return _err(
                "render_settings needs settings. The shape is Resolve's "
                "PhotoRenderSettings: see the API stubs "
                "(search_scripting_api 'PhotoRenderSettings')."
            )
        ok, _who, err = _call_any(_photo_objs(proj, mp), "SetPhotoRenderSettings", settings)
        if err or ok is None:
            return _err(err or "SetPhotoRenderSettings returned nothing.")
        if ok is False:
            return _err("SetPhotoRenderSettings returned False.")
        return _ok(applied=settings)

    # ---- photos in an album --------------------------------------------
    if action in ("photos", "add_photos", "remove_photos", "current_item", "stills"):
        # add_photos addresses the album via current album or name
        if action == "add_photos":
            ids = p.get("clip_ids")
            if not ids:
                return _err("add_photos needs clip_ids.")
            items = []
            root = mp.GetRootFolder()
            for cid in ids:
                c = _find_clip_recursive(root, cid)
                if not c:
                    return _err(f"No media pool clip with id '{cid}'.")
                items.append(c)
            # AddToPhotoAlbum appends to the CURRENT album.
            target, terr = _resolve_album(proj, mp, p.get("album_id"), p.get("name"))
            if terr and (p.get("album_id") or p.get("name")):
                return terr
            if target:
                _call_any(_photo_objs(proj, mp), "SetCurrentPhotoAlbum", target)

            album_now, _w, _e = _call_any(_photo_objs(proj, mp), "GetCurrentPhotoAlbum")
            before = len((album_now.GetPhotoList() or [])) if album_now else None

            res, _who, err = _call_any(_photo_objs(proj, mp), "AddToPhotoAlbum", items)

            # Verify by reading back — do NOT trust the call.
            after_album, _w2, _e2 = _call_any(_photo_objs(proj, mp), "GetCurrentPhotoAlbum")
            after = len((after_album.GetPhotoList() or [])) if after_album else None
            added = []
            for it in (res or []):
                try:
                    added.append({"name": it.GetName(), "id": it.GetUniqueId()})
                except Exception:
                    pass

            if not added and before is not None and after is not None and after <= before:
                return _err(
                    "AddToPhotoAlbum added NOTHING (before=%s, after=%s) and "
                    "returned %r. MEASURED on Resolve 21.1.2.10: this call is "
                    "BROKEN — tested four ways (immediately after "
                    "CreateEmptyPhotoAlbum, with a 2 s pause, after an explicit "
                    "SetCurrentPhotoAlbum that GetCurrentPhotoAlbum confirmed, "
                    "and with a fresh album each time); every run added zero "
                    "photos and returned an empty list. Use "
                    "photo_albums(action='create_from_photos', name=…, "
                    "clip_ids=…) instead — that path VERIFIED working "
                    "(2 photos added and read back)."
                    % (before, after, res)
                )
            return _ok(added=added, count=len(added),
                       album=album_now.GetName() if album_now else None)

        album, aerr = _resolve_album(proj, mp, p.get("album_id"), p.get("name"))
        if aerr:
            return aerr

        if action == "photos":
            lst = album.GetPhotoList() or []
            out = []
            for it in lst:
                out.append({
                    "name": it.GetName(),
                    "id": it.GetUniqueId(),
                    "rating": it.GetRatings(),
                    "flags": it.GetFlagList(),
                })
            return _ok(photos=out, count=len(out), album=album.GetName())

        if action == "current_item":
            it = album.GetCurrentItem()
            if not it:
                return _ok(photo=None)
            return _ok(photo={"name": it.GetName(), "id": it.GetUniqueId()})

        if action == "remove_photos":
            ids = p.get("photo_ids")
            if not ids:
                return _err("remove_photos needs photo_ids.")
            lst = album.GetPhotoList() or []
            by_id = {}
            for it in lst:
                by_id[it.GetUniqueId()] = it
            targets = [by_id[i] for i in ids if i in by_id]
            if not targets:
                return _err(f"None of {ids} are in album '{album.GetName()}'.")
            ok = album.DeletePhotos(targets)
            if not ok:
                return _err("DeletePhotos returned False.")
            remaining = album.GetPhotoList() or []
            return _ok(removed=len(targets), remaining=len(remaining))

        if action == "stills":
            if p.get("all_photos"):
                st = album.GrabAllStills()
                return _ok(grabbed=len(st or []), grabbed_all=True)
            st = album.GrabStill()
            return _ok(grabbed=1 if st else 0, grabbed_all=False)

    # ---- per-photo properties ------------------------------------------
    PHOTO_ACTIONS = {
        "photo", "rate", "flag", "clip_color", "versions", "add_version",
        "load_version", "delete_version", "copy_grade", "effects_list",
        "effect_apply", "effect_remove", "fusion_comps", "fusion_add",
    }
    if action in PHOTO_ACTIONS:
        photo = None
        pid = p.get("photo_id")
        pname = p.get("photo_name")
        album = None
        if p.get("album_id") or p.get("name") or action == "copy_grade":
            album, aerr = _resolve_album(proj, mp, p.get("album_id"), p.get("name"))
            if aerr and action != "copy_grade":
                return aerr
        if not album:
            album, _w, _e = _call_any(_photo_objs(proj, mp), "GetCurrentPhotoAlbum")
        if album is None:
            return _err("No photo album found. Pass album_id/name or set a current album.")

        if pid or pname:
            lst = album.GetPhotoList() or []
            for it in lst:
                if (pid and it.GetUniqueId() == pid) or (pname and it.GetName() == pname):
                    photo = it
                    break
            if photo is None:
                return _err(f"Photo '{pid or pname}' not found in album '{album.GetName()}'.")
        else:
            photo = album.GetCurrentItem()
            if photo is None:
                return _err("No photo addressed. Pass photo_id/photo_name, or select one.")

        if action == "photo":
            return _ok(photo={
                "name": photo.GetName(),
                "id": photo.GetUniqueId(),
                "rating": photo.GetRatings(),
                "flags": photo.GetFlagList(),
                "clip_color": photo.GetClipColor(),
                "versions": photo.GetVersionNameList(),
                "current_version": photo.GetCurrentVersion(),
                "fusion_comp_count": photo.GetFusionCompCount(),
            })

        if action == "rate":
            stars = p.get("stars")
            if stars is None:
                return _err("rate needs stars (0-5).")
            want = max(0, min(5, int(stars)))
            photo.SetRatings(want)
            got = photo.GetRatings()
            if got != want:
                return _err(f"SetRatings({want}) silently gave {got}.")
            return _ok(rating=got)

        if action == "flag":
            if p.get("clear"):
                ok = photo.ClearFlags(p.get("color") or "All")
                if not ok:
                    return _err("ClearFlags returned False.")
                return _ok(flags=photo.GetFlagList())
            color = p.get("color")
            if not color:
                return _err("flag needs color, or clear=true.")
            ok = photo.AddFlag(color)
            if not ok:
                return _err(
                    f"AddFlag('{color}') returned False — valid colours are "
                    "Resolve's FlagColor values (Blue, Cyan, Green, Yellow, "
                    "Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, "
                    "Lemon, Sand, Cocoa, Cream)."
                )
            return _ok(flags=photo.GetFlagList())

        if action == "clip_color":
            if p.get("clear"):
                photo.ClearClipColor()
                return _ok(clip_color=photo.GetClipColor())
            color = p.get("color")
            if not color:
                return _err("clip_color needs color, or clear=true.")
            ok = photo.SetClipColor(color)
            if not ok:
                return _err(
                    f"SetClipColor('{color}') returned False — the colour name "
                    "must match Resolve's ClipColor values (e.g. Orange, "
                    "Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, "
                    "Purple, Violet, Pink, Tan, Beige, Brown, Chocolate)."
                )
            return _ok(clip_color=photo.GetClipColor())

        if action == "versions":
            return _ok(versions=photo.GetVersionNameList(), current=photo.GetCurrentVersion())

        if action == "add_version":
            vn = p.get("version_name")
            if not vn:
                return _err("add_version needs version_name.")
            ok = photo.AddVersion(vn)
            if not ok:
                return _err(f"AddVersion('{vn}') returned False (name must be unique).")
            return _ok(versions=photo.GetVersionNameList())

        if action == "load_version":
            vn = p.get("version_name")
            if not vn:
                return _err("load_version needs version_name.")
            ok = photo.LoadVersionByName(vn)
            if not ok:
                return _err(f"LoadVersionByName('{vn}') returned False.")
            return _ok(current=photo.GetCurrentVersion())

        if action == "delete_version":
            vn = p.get("version_name")
            if not vn:
                return _err("delete_version needs version_name.")
            ok = photo.DeleteVersionByName(vn)
            if not ok:
                return _err(f"DeleteVersionByName('{vn}') returned False.")
            return _ok(versions=photo.GetVersionNameList())

        if action == "copy_grade":
            ok = photo.CopyGrades([photo])
            return _ok(copied=bool(ok), note="PhotoAlbumItem.CopyGrades")

        if action == "effects_list":
            cat = p.get("category")
            cats = [cat] if cat else ["ofx", "fusion"]
            found = []
            for c in cats:
                try:
                    for e in (photo.GetEffects(c) or []):
                        found.append(_effect_info(e))
                except Exception as exc:
                    found.append({"category": c, "error": str(exc)})
            return _ok(effects=found, count=len(found))

        if action == "effect_apply":
            cat, eid = p.get("category"), p.get("id")
            if not cat or not eid:
                return _err("effect_apply needs category ('ofx'|'fusion') and id.")
            eff = photo.AddEffect(cat, eid)
            if not eff:
                return _err(f"AddEffect('{cat}','{eid}') returned None.")
            return _ok(effect=_effect_info(eff))

        if action == "effect_remove":
            cat = p.get("category")
            if not cat:
                return _err("effect_remove needs category.")
            current = photo.GetEffects(cat) or []
            idxs = p.get("indices")
            if idxs:
                by_index = {}
                for e in current:
                    try:
                        by_index[e.GetIndex()] = e
                    except Exception:
                        pass
                targets = [by_index[i] for i in idxs if i in by_index]
            else:
                targets = list(current)
            if not targets:
                return _ok(removed=0, note=f"No '{cat}' effects on the photo.")
            ok = photo.DeleteEffects(targets)
            if not ok:
                return _err("DeleteEffects returned False.")
            return _ok(removed=len(targets))

        if action == "fusion_comps":
            names = photo.GetFusionCompNameList()
            return _ok(comps=names, count=photo.GetFusionCompCount())

        if action == "fusion_add":
            comp = photo.AddFusionComp()
            if not comp:
                return _err("AddFusionComp returned nothing.")
            return _ok(comps=photo.GetFusionCompNameList(),
                       count=photo.GetFusionCompCount())

    return _err(
        f"Unknown action '{action}'. Album actions: list, current, set_current, "
        "create, create_from_photos, delete, rename, quick_export_presets, "
        "render_settings, photos, add_photos, remove_photos, current_item, "
        "stills. Photo actions: photo, rate, flag, clip_color, versions, "
        "add_version, load_version, delete_version, copy_grade, effects_list, "
        "effect_apply, effect_remove, fusion_comps, fusion_add."
    )


@mcp.tool()
def node_graph(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Node graph inspection and labelling, on a clip or a photo (21.1.2+).

    Verified working on 21.1.2.10: GetNodeLabel, SetNodeLabel, GetNodeColor,
    SetNodeColor, SetNodeEnabled, GetNumNodes, ResetAllGrades, ResetAllNodeColors.
    SetLUT/GetLUT returned False/None in testing (a LUT path is required and
    must exist) — the tool reports what it gets rather than assuming.

    Target: pass `item_id`/`name` for a timeline clip, or `photo_id` for a photo
    album item. `clip_id` is accepted but NOT usable on 21.1.2.10:
    MediaPoolItem.GetNodeGraph is not callable there, while the timeline and
    photo variants both work.

    Actions:
      info(item_id?|name?|photo_id?|clip_id?, track_type?, track_index?)
        -> {num_nodes, nodes: [{index, label, color, enabled}]}
      label(node_index, label, ...) -> {success, nodes}
        — SetNodeLabel. Pass an empty string to clear.
      color(node_index, color, ...) -> {success, nodes}
        — SetNodeColor. Valid names: Orange, Apricot, Yellow, Lime, Olive,
          Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Brown,
          Chocolate. An empty string clears the color.
      enable(node_index, enabled, ...) -> {success, nodes}
      tools(node_index, ...) -> {tools}
        — which Fusion/OFX tools sit in that node.
      lut(node_index, lut_path?, ...) -> {success, lut}
        — read, or set when lut_path is given (Resolve's relative LUT path).
      cache(node_index, mode?, ...) -> {success, cache_mode}
      reset_colors(...) -> {success}
      reset_grades(...) -> {success}   — destructive: clears the whole grade.
    """
    p = params or {}
    ctx, err = _ctx()
    if err:
        return err
    _, _, proj, tl = ctx
    mp = proj.GetMediaPool()

    # --- resolve the graph -------------------------------------------------
    graph = None
    origin = None

    if p.get("photo_id"):
        album, _w, _e = _call_any(_photo_objs(proj, mp), "GetCurrentPhotoAlbum")
        if album is None:
            return _err("No current photo album for photo_id lookup.")
        for it in (album.GetPhotoList() or []):
            if it.GetUniqueId() == p["photo_id"]:
                graph = it.GetNodeGraph()
                origin = f"photo {it.GetName()}"
                break
        if graph is None:
            return _err(f"No photo with id '{p['photo_id']}' in the current album.")

    elif p.get("clip_id"):
        c = _find_clip_recursive(mp.GetRootFolder(), p["clip_id"])
        if not c:
            return _err(f"No media pool clip with id '{p['clip_id']}'.")
        fn = getattr(c, "GetNodeGraph", None)
        if fn is None:
            return _err(
                "MediaPoolItem.GetNodeGraph is not available on Resolve "
                "21.1.2.10 (measured: the attribute is not callable, while "
                "TimelineItem.GetNodeGraph and PhotoAlbumItem.GetNodeGraph "
                "both work). Add the clip to a timeline and address it with "
                "item_id instead, or pass photo_id for a photo album item."
            )
        try:
            graph = fn()
        except TypeError:
            return _err(
                "MediaPoolItem.GetNodeGraph is not callable on Resolve "
                "21.1.2.10. Put the clip on a timeline and use item_id, or "
                "pass photo_id for a photo album item."
            )
        origin = f"media pool clip {c.GetName()}"

    else:
        if tl is None:
            return _err("No timeline open — pass photo_id or clip_id instead.")
        item, ierr = _find_item(
            tl, item_id=p.get("item_id"),
            track_type=p.get("track_type", "video"),
            track_index=int(p.get("track_index", 1)),
            name=p.get("name"),
        )
        if ierr:
            return ierr
        graph = item.GetNodeGraph()
        origin = f"timeline item {item.GetName()}"

    if graph is None:
        return _err("Could not obtain a node graph for that target.")

    def _g(method, *args):
        """Call a Graph method, tolerating ones this graph type does not have.

        Measured on 21.1.2.10: a photo album item's graph answers
        ResetAllNodeColors while a timeline clip's graph raises
        'NoneType object is not callable' for it. Graph capability varies by
        where the graph came from, so every call reports its own failure.
        """
        fn = getattr(graph, method, None)
        if fn is None:
            return None, f"Graph.{method} is missing on this graph."
        try:
            return fn(*args), None
        except TypeError as exc:
            if "not callable" in str(exc):
                return None, (
                    f"Graph.{method} is not available on a graph from this "
                    f"target ({origin}). Measured on 21.1.2.10: it exists on "
                    "photo album graphs but not on timeline clip graphs."
                )
            return None, f"Graph.{method}: {exc}"
        except Exception as exc:
            return None, f"Graph.{method}: {exc}"

    def _snapshot():
        out = []
        n, err = _g("GetNumNodes")
        if err or n is None:
            return out
        for i in range(1, int(n) + 1):
            entry = {"index": i}
            lab, _e1 = _g("GetNodeLabel", i)
            col, _e2 = _g("GetNodeColor", i)
            entry["label"] = lab
            entry["color"] = col
            out.append(entry)
        return out

    idx = p.get("node_index")

    if action == "info":
        nodes = _snapshot()
        return _ok(target=origin, num_nodes=len(nodes), nodes=nodes)

    if action in ("label", "color", "enable", "tools", "lut", "cache"):
        if idx is None:
            return _err(f"{action} needs node_index (1-based).")
        idx = int(idx)

    if action == "label":
        label = p.get("label")
        if label is None:
            return _err("label needs label (an empty string clears it).")
        res, err = _g("SetNodeLabel", idx, label)
        if err or res is False:
            n_nodes, _e = _g("GetNumNodes")
            return _err(err or (
                f"SetNodeLabel({idx}, '{label}') returned False — node_index "
                f"must be 1..{n_nodes}."
            ))
        return _ok(nodes=_snapshot())

    if action == "color":
        color = p.get("color")
        if color is None:
            return _err("color needs color (an empty string clears it).")
        res, err = _g("SetNodeColor", idx, color)
        if err or res is False:
            return _err(err or (
                f"SetNodeColor({idx}, '{color}') returned False. Check the "
                "node_index range and the colour name (Orange, Apricot, "
                "Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, "
                "Pink, Tan, Beige, Brown, Chocolate; empty string clears)."
            ))
        return _ok(nodes=_snapshot())

    if action == "enable":
        enabled = p.get("enabled")
        if enabled is None:
            return _err("enable needs enabled (bool).")
        res, err = _g("SetNodeEnabled", idx, bool(enabled))
        if err or res is False:
            return _err(err or f"SetNodeEnabled({idx}, {enabled}) returned False.")
        return _ok(nodes=_snapshot())

    if action == "tools":
        res, err = _g("GetToolsInNode", idx)
        if err:
            return _err(err)
        return _ok(node_index=idx, tools=res)

    if action == "lut":
        lut_path = p.get("lut_path")
        if lut_path is None:
            lut, err = _g("GetLUT", idx)
            if err:
                return _err(err)
            return _ok(node_index=idx, lut=lut)
        res, err = _g("SetLUT", idx, lut_path)
        if err or res is False:
            return _err(err or (
                f"SetLUT({idx}, '{lut_path}') returned False — the path must be "
                "a LUT Resolve can resolve (relative to the master LUT root). "
                "See the `lut` tool's list action for valid names."
            ))
        lut, _e = _g("GetLUT", idx)
        return _ok(node_index=idx, lut=lut)

    if action == "cache":
        mode = p.get("mode")
        if mode is None:
            cm, err = _g("GetNodeCacheMode", idx)
            if err:
                return _err(err)
            return _ok(node_index=idx, cache_mode=cm)
        res, err = _g("SetNodeCacheMode", idx, mode)
        if err or res is False:
            return _err(err or f"SetNodeCacheMode({idx}, {mode}) returned False.")
        cm, _e = _g("GetNodeCacheMode", idx)
        return _ok(node_index=idx, cache_mode=cm)

    if action == "reset_colors":
        res, err = _g("ResetAllNodeColors")
        if err or res is False:
            return _err(err or "ResetAllNodeColors returned False.")
        return _ok(nodes=_snapshot())

    if action == "reset_grades":
        if not p.get("confirm"):
            return _err(
                "reset_grades is DESTRUCTIVE — it clears the whole grade on "
                "every node. Pass confirm=true to proceed."
            )
        res, err = _g("ResetAllGrades")
        if err or res is False:
            return _err(err or "ResetAllGrades returned False.")
        return _ok(nodes=_snapshot())

    return _err(
        f"Unknown action '{action}'. Use info, label, color, enable, tools, "
        "lut, cache, reset_colors or reset_grades."
    )


@mcp.tool()
def project_extras(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Project-level gaps: render presets, audio render formats, transcription.

    Three surfaces the mainstream servers do not implement, all verified
    present on Resolve 21.1.2.10 by calling them (the type stubs list them, but
    a stub only says a name exists — see CONTRIBUTING.md).

    Render presets:
      render_presets() -> {presets}
        — GetRenderPresetList. Verified: returns the real list.
      update_render_preset(preset_name) -> {success, preset}
        — UpdateRenderPreset: overwrite a saved preset with the CURRENT render
          settings. MEASURED on 21.1.2.10: returns False for the 37 factory
          presets GetRenderPresetList reports (e.g. 'H.264 Master'), so this
          only has a chance against a preset saved from the Render page in the
          GUI. Project.SaveRenderPreset does NOT exist in the API, so a preset
          cannot be created from here to test with. Treat as GUI-dependent.
      quick_export_enable(preset_name, enabled) -> {success}
        — SetQuickExportEnabledForRenderPreset. Same limitation: False for
          factory presets on this build.

    Audio render formats:
      audio_formats() -> {formats}
        — GetAudioRenderFormats: {display name -> file extension}.
      audio_codecs(format_extension) -> {codecs}
        — GetAudioRenderCodecs: {codec description -> codec name} for a format
          extension such as 'wav', 'mov', 'mxf'.

    Transcription (a clip's speech-to-text content):
      transcription(clip_id, use_nested?) -> {transcription}
        — GetTranscription. `use_nested` reads a nested timeline's transcript.
      set_transcription(clip_id, transcription) -> {success, verified}
        — SetTranscription. REPLACES an existing transcript. MEASURED on
          21.1.2.10: returns False for a PNG still AND for a real video clip
          that had no transcript, with both '01:00:00:00' and '00:00:00:00'
          start timecodes — it appears unable to create a transcript where none
          exists. Produce one in the Edit page (AI Transcription) first, then
          this can replace it. The shape is:
            {language: "en", segments: [{start: "01:00:02:05",
                                         end:   "01:00:04:10",
                                         text:  "hello there",
                                         speaker: "Name" | None}, ...]}
          Timecodes are absolute strings. The tool re-reads the clip afterwards
          and reports whether the new text actually landed.

    Also reports which of these the running Resolve build answers at all —
    capability here varies by build, so nothing is assumed.
    """
    p = params or {}
    ctx, err = _ctx()
    if err:
        return err
    _, _, proj, _ = ctx
    mp = proj.GetMediaPool()

    if action == "capabilities":
        def _has(obj, name):
            fn = getattr(obj, name, None)
            if fn is None:
                return False
            try:
                fn()
                return True
            except TypeError as exc:
                return "not callable" not in str(exc)
            except Exception:
                return True
        return _ok(surfaces={
            "Project.GetRenderPresetList": _has(proj, "GetRenderPresetList"),
            "Project.UpdateRenderPreset": _has(proj, "UpdateRenderPreset"),
            "Project.SetQuickExportEnabledForRenderPreset": _has(
                proj, "SetQuickExportEnabledForRenderPreset"),
            "Project.GetAudioRenderFormats": _has(proj, "GetAudioRenderFormats"),
            "Project.GetAudioRenderCodecs": _has(proj, "GetAudioRenderCodecs"),
            "MediaPoolItem.GetTranscription": True,
            "MediaPoolItem.SetTranscription": True,
        }, note="Probed by calling, because hasattr lies on Resolve's proxy objects.")

    if action == "render_presets":
        fn = getattr(proj, "GetRenderPresetList", None)
        if fn is None:
            return _err("This build does not expose GetRenderPresetList.")
        try:
            presets = fn()
        except TypeError:
            return _err("GetRenderPresetList is not callable on this build.")
        return _ok(presets=presets or [])

    if action == "update_render_preset":
        name = p.get("preset_name")
        if not name:
            return _err("update_render_preset needs preset_name.")
        fn = getattr(proj, "UpdateRenderPreset", None)
        if fn is None:
            return _err("This build does not expose UpdateRenderPreset.")
        try:
            ok = fn(name)
        except TypeError:
            return _err("UpdateRenderPreset is not callable on this build.")
        if not ok:
            return _err(
                f"UpdateRenderPreset('{name}') returned False — the preset must "
                "already exist. See render_presets for the available names."
            )
        return _ok(preset=name)

    if action == "quick_export_enable":
        name, enabled = p.get("preset_name"), p.get("enabled")
        if not name or enabled is None:
            return _err("quick_export_enable needs preset_name and enabled.")
        fn = getattr(proj, "SetQuickExportEnabledForRenderPreset", None)
        if fn is None:
            return _err("This build does not expose SetQuickExportEnabledForRenderPreset.")
        try:
            ok = fn(name, bool(enabled))
        except TypeError:
            return _err("SetQuickExportEnabledForRenderPreset is not callable on this build.")
        if not ok:
            return _err(
                f"SetQuickExportEnabledForRenderPreset('{name}', {enabled}) "
                "returned False — the preset must already exist."
            )
        return _ok(preset=name, quick_export=bool(enabled))

    if action == "audio_formats":
        fn = getattr(proj, "GetAudioRenderFormats", None)
        if fn is None:
            return _err("This build does not expose GetAudioRenderFormats.")
        try:
            res = fn()
        except TypeError:
            return _err("GetAudioRenderFormats is not callable on this build.")
        return _ok(formats=res or {})

    if action == "audio_codecs":
        ext = p.get("format_extension")
        if not ext:
            return _err("audio_codecs needs format_extension, e.g. 'wav'.")
        fn = getattr(proj, "GetAudioRenderCodecs", None)
        if fn is None:
            return _err("This build does not expose GetAudioRenderCodecs.")
        try:
            res = fn(ext)
        except TypeError:
            return _err("GetAudioRenderCodecs is not callable on this build.")
        if not res:
            return _err(
                f"GetAudioRenderCodecs('{ext}') returned nothing — pass an "
                "extension from audio_formats (e.g. wav, mov, mxf, flac)."
            )
        return _ok(format_extension=ext, codecs=res)

    if action in ("transcription", "set_transcription"):
        cid = p.get("clip_id")
        if not cid:
            return _err(f"{action} needs clip_id.")
        clip = _find_clip_recursive(mp.GetRootFolder(), cid)
        if not clip:
            return _err(f"No media pool clip with id '{cid}'.")

        if action == "transcription":
            fn = getattr(clip, "GetTranscription", None)
            if fn is None:
                return _err("This build does not expose MediaPoolItem.GetTranscription.")
            try:
                res = fn(bool(p.get("use_nested", False)))
            except TypeError:
                return _err("GetTranscription is not callable on this build.")
            if not res:
                return _ok(
                    transcription=None,
                    note=(
                        "This clip has no transcript yet. Create one in the "
                        "Edit page (AI Transcription) or via the timeline_ai "
                        "tool, then read it here."
                    ),
                )
            return _ok(transcription=res)

        # set_transcription
        tr = p.get("transcription")
        if not isinstance(tr, dict) or "segments" not in tr:
            return _err(
                "set_transcription needs transcription={'language': …, "
                "'segments': [{'start': '01:00:02:05', 'end': …, 'text': …}, …]}. "
                "Timecodes are absolute strings."
            )
        segs = tr.get("segments")
        if not isinstance(segs, list) or not segs:
            return _err("transcription['segments'] must be a non-empty list.")
        for i, s in enumerate(segs):
            if not isinstance(s, dict) or not all(k in s for k in ("start", "end", "text")):
                return _err(
                    f"segment {i} needs start, end and text "
                    f"(got keys {sorted(s) if isinstance(s, dict) else type(s).__name__})."
                )
        fn = getattr(clip, "SetTranscription", None)
        if fn is None:
            return _err("This build does not expose MediaPoolItem.SetTranscription.")
        try:
            ok = fn(tr)
        except TypeError:
            return _err("SetTranscription is not callable on this build.")
        if not ok:
            return _err(
                "SetTranscription returned False. The timecodes must lie inside "
                "the clip and be absolute strings ('01:00:02:05')."
            )
        # verify by reading back — do not trust the call
        check = getattr(clip, "GetTranscription", None)
        verified = None
        want = segs[0].get("text")
        if check:
            got = check(False) or {}
            gsegs = got.get("segments") or []
            verified = bool(gsegs) and (gsegs[0].get("text") == want)
            return _ok(segments_written=len(segs), verified=verified,
                       read_back=gsegs[:2],
                       note=None if verified else
                       "The call reported success but the first segment's text "
                       "did not read back as written — treat as unverified.")
        return _ok(segments_written=len(segs), verified=None,
                   note="Could not read back (GetTranscription unavailable).")

    return _err(
        f"Unknown action '{action}'. Use capabilities, render_presets, "
        "update_render_preset, quick_export_enable, audio_formats, "
        "audio_codecs, transcription or set_transcription."
    )


@mcp.tool()
def camera_comparison(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Lay out a multi-camera comparison timeline (Insta360 grid / split views).

    Reproduces the camera-comparison workflow this project has been running as
    loose scripts, with the position bug fixed.

    **The bug worth knowing:** those scripts set the image position with
    `SetProperty("PositionX", …)` / `"PositionY"`. MEASURED on 21.1.2.10 those
    keys return **False and are silently ignored** — `GetProperty` gives back
    `False` too. The real keys are **`Pan`** (x, +right) and **`Tilt`** (y,
    +up), in pixels. Zoom worked in those scripts; positioning never did. This
    tool uses Pan/Tilt and verifies each write by reading it back.

    Camera detection from the clip name, longest prefix first:

      ace*   -> Insta360 AcePro       (marker Orange)
      go*    -> Insta360 Go Ultra     (marker Green)
      luna*  -> Insta360 Luna Ultra   (marker Cyan)
      x*     -> Insta360 X5           (marker Blue)
      vid_*  -> Handy                 (marker Gray)
                 (an Android file, e.g. VID_20260614_170228.mp4)

    Actions:
      detect(track_type?, track_index?) -> {clips: [{name, id, camera}], unknown}
        — what this timeline holds and which camera each clip is. Run this
          first: it tells you whether the names match the convention.
      grid_2x2(track_type?, track_index?, scale?, verify?)
        -> {applied, skipped, layout}
        — place the four cameras in a 2x2 quadrant grid. Quadrant centres are
          at ±25 % of each axis; default scale 0.5.
      split_h / split_v(track_type?, track_index?, scale?)
        -> {applied, layout}
        — two-up side by side (left/right) or stacked (top/bottom).
      layout(assignments, track_type?, track_index?, scale?)
        -> {applied, results}
        — explicit control. assignments maps a clip_id (or camera name) to
          {x?, y?, scale?}, where x/y are fractions of the timeline raster
          (+x right, +y up) and scale multiplies the 1.0 zoom.
      fullframe(clip_ids?|cameras?, track_type?, track_index?)
        -> {reset}
        — back to 1.0 zoom and centred, for the "phone as full picture" clip.
      markers(track_type?, track_index?, duration_from_clip?)
        -> {added, by_camera, markers_in_timeline, failed?}
        — timeline markers naming each clip's camera, coloured per camera.
          `added` and `markers_in_timeline` are both reported so the caller can
          see they agree. LIMITATION, measured on 21.1.2.10: a marker on the
          clip at timeline position 0 cannot be placed — neither the relative
          frame (0) nor the absolute one (StartFrame + 0) is accepted, while
          every other clip answers. Those clips are listed in `failed` instead
          of being silently skipped.
      sort_to_bins(folder_name?, recursive?, prefix?)
        -> {moved, bins, skipped}
        — file clips into per-camera bins by their name prefix. `folder_name`
          names an existing folder to sort inside; without it the media pool
          root is used. Bins are created on demand.
      build_timeline(name?, cameras?, scene_gap_frames?, sync_at?)
        -> {timeline, placed, by_camera}
        — build the multi-track comparison: one video track per camera, each
          scene's clips stacked at the same frame so they play side by side.
          `cameras` limits which cameras take part. `scene_gap_frames`
          (default 0) inserts a gap between scenes; `sync_at` (default 0) is
          the frame the first scene starts on.
      read(track_type?, track_index?) -> {clips: [{name, camera, zoom, pan, tilt}]}
        — the current transform of every clip, so you can see what a call did.

    Note on the media-pool API, measured: AddSubFolder and MoveClips live on
    **MediaPool**, not on Folder — `Folder.AddSubFolder` and `Folder.MoveClips`
    do not exist (the same split as the photo-album API). MoveClips was
    verified to actually relocate the clip, not merely return True.

    Everything reports what actually happened: each SetProperty is read back,
    and a write that does not stick is counted as a failure rather than a
    success.
    """
    p = params or {}
    ctx, err = _ctx()
    if err:
        return err
    _, _, proj, tl = ctx
    mp = proj.GetMediaPool()
    if tl is None:
        return _err("No current timeline.")

    track_type = p.get("track_type", "video")
    track_index = int(p.get("track_index", 1))
    res_x, res_y = _timeline_pixels(proj)

    def _items():
        return tl.GetItemListInTrack(track_type, track_index) or []

    def _select(ids=None, cameras=None, names=None):
        """Pick items by id, by camera name, or by clip name."""
        out = []
        for it in _items():
            n = it.GetName()
            cam_name, _col = _camera_of(n)
            if ids and it.GetUniqueId() in ids:
                out.append(it)
            elif cameras and cam_name in cameras:
                out.append(it)
            elif names and n in names:
                out.append(it)
        return out

    def _apply(it, x=None, y=None, scale=None, verify=True):
        """Set the transform, reading every write back."""
        wrote = {}
        if scale is not None:
            for key in ("ZoomX", "ZoomY"):
                try:
                    it.SetProperty(key, float(scale))
                    wrote[key] = it.GetProperty(key)
                except Exception as exc:
                    wrote[key] = f"error: {exc}"
        if x is not None:
            try:
                it.SetProperty("Pan", float(x))
                wrote["Pan"] = it.GetProperty("Pan")
            except Exception as exc:
                wrote["Pan"] = f"error: {exc}"
        if y is not None:
            try:
                it.SetProperty("Tilt", float(y))
                wrote["Tilt"] = it.GetProperty("Tilt")
            except Exception as exc:
                wrote["Tilt"] = f"error: {exc}"
        ok = True
        if verify:
            for k, v in wrote.items():
                if isinstance(v, str) or v is False:
                    ok = False
                if scale is not None and k.startswith("Zoom") and v != float(scale):
                    ok = False
        return ok, wrote

    # ------------------------------------------------------------------
    if action == "detect":
        clips, unknown = [], []
        for it in _items():
            n = it.GetName()
            cam_name, color = _camera_of(n)
            entry = {"name": n, "id": it.GetUniqueId(), "camera": cam_name}
            if cam_name:
                entry["marker_color"] = color
                clips.append(entry)
            else:
                unknown.append(n)
        return _ok(clips=clips, count=len(clips), unknown=unknown,
                   timeline=tl.GetName(), resolution=[res_x, res_y])

    if action == "read":
        out = []
        for it in _items():
            cam_name, _c = _camera_of(it.GetName())
            out.append({
                "name": it.GetName(),
                "id": it.GetUniqueId(),
                "camera": cam_name,
                "zoom_x": it.GetProperty("ZoomX"),
                "zoom_y": it.GetProperty("ZoomY"),
                "pan": it.GetProperty("Pan"),
                "tilt": it.GetProperty("Tilt"),
            })
        return _ok(clips=out, count=len(out), resolution=[res_x, res_y])

    if action in ("grid_2x2", "split_h", "split_v"):
        scale = float(p.get("scale", 0.5))
        if action == "grid_2x2":
            plan = GRID_2X2
        elif action == "split_h":
            plan = {"ace": (-0.25, 0.0), "go": (0.25, 0.0),
                    "luna": (-0.25, 0.0), "x": (0.25, 0.0)}
        else:
            plan = {"ace": (0.0, 0.25), "go": (0.0, 0.25),
                    "luna": (0.0, -0.25), "x": (0.0, -0.25)}

        applied, skipped, failed = [], [], []
        for it in _items():
            cam_name, _c = _camera_of(it.GetName())
            key = next((k for k, (nm, _col) in CAMERA_PREFIXES.items()
                        if nm == cam_name), None)
            if key is None or key not in plan:
                skipped.append(it.GetName())
                continue
            fx, fy = plan[key]
            ok, wrote = _apply(it, x=fx * res_x, y=fy * res_y, scale=scale)
            (applied if ok else failed).append({
                "name": it.GetName(), "camera": cam_name,
                "requested": {"pan": fx * res_x, "tilt": fy * res_y, "scale": scale},
                "read_back": wrote,
            })
        result = _ok(applied=applied, count=len(applied),
                     layout=action, resolution=[res_x, res_y], scale=scale)
        if skipped:
            result["skipped"] = skipped
        if failed:
            result["warning"] = (
                f"{len(failed)} clip(s) did NOT take their transform — a "
                "SetProperty did not read back as written. See failed."
            )
            result["failed"] = failed
        return result

    if action == "layout":
        assignments = p.get("assignments")
        if not isinstance(assignments, dict) or not assignments:
            return _err(
                "layout needs assignments={clip_id_or_camera_name: "
                "{x?, y?, scale?}} where x/y are fractions of the timeline "
                "raster (+x right, +y up) and scale multiplies 1.0 zoom."
            )
        scale_default = float(p.get("scale", 1.0))
        results = []
        for target, spec in assignments.items():
            by_id = _select(ids=[target])
            items = by_id or _select(cameras=[target]) or _select(names=[target])
            if not items:
                results.append({"target": target, "error": "not found"})
                continue
            for it in items:
                x = spec.get("x")
                y = spec.get("y")
                sc = spec.get("scale")
                ok, wrote = _apply(
                    it,
                    x=x * res_x if x is not None else None,
                    y=y * res_y if y is not None else None,
                    scale=sc if sc is not None else scale_default,
                )
                results.append({
                    "target": target, "name": it.GetName(),
                    "success": ok, "read_back": wrote,
                })
        bad = [r for r in results if not r.get("success")]
        out = _ok(results=results, applied=len(results) - len(bad))
        if bad:
            out["warning"] = f"{len(bad)} item(s) did not take the transform."
        return out

    if action == "fullframe":
        targets = _select(
            ids=p.get("clip_ids"),
            cameras=p.get("cameras"),
            names=p.get("names"),
        )
        if not targets:
            if p.get("clip_ids") or p.get("cameras") or p.get("names"):
                return _err("None of the given targets are on that track.")
            return _err(
                "fullframe needs clip_ids, cameras or names — refusing to reset "
                "every clip in the timeline by accident."
            )
        results = []
        for it in targets:
            ok, wrote = _apply(it, x=0.0, y=0.0, scale=1.0)
            results.append({"name": it.GetName(), "success": ok, "read_back": wrote})
        return _ok(reset=results, count=len(results))

    if action == "markers":
        from_clip = bool(p.get("duration_from_clip", True))
        added, by_camera, failed = 0, {}, []

        def _marker_at(frame_id, color, name, note, dur):
            """Place a timeline marker, tolerating both frame bases.

            CORRECTED on re-measurement (verified by reading tl.GetMarkers()
            back, not by the return value): Timeline.AddMarker(0) DOES work.
            An earlier version of this file claimed the clip at timeline
            position 0 refused a relative frame; that was a bad measurement.
            The call that returns True and writes nothing is
            TimelineItem.AddMarker on that same clip — which is why markers
            here go through the TIMELINE, never through the item.

            The relative frame is tried first and the absolute frame kept as a
            fallback, because neither base is documented anywhere.
            """
            base = int(tl.GetStartFrame() or 0)
            for candidate, label in ((int(frame_id), "relative"),
                                     (base + int(frame_id), "absolute")):
                try:
                    if tl.AddMarker(candidate, color, name, note, dur, ""):
                        return True, label
                except Exception:
                    continue
            return False, None

        for it in _items():
            name = it.GetName()
            cam_name, color = _camera_of(name)
            if not cam_name:
                continue
            dur = it.GetDuration() if from_clip else 0
            ok, base_used = _marker_at(
                it.GetStart(), color, cam_name,
                f"Camera: {cam_name}\nClip: {name}", int(dur or 0),
            )
            if ok:
                added += 1
                by_camera[cam_name] = by_camera.get(cam_name, 0) + 1
            else:
                failed.append(name)

        # Verify against the timeline's own marker list, not our counter.
        read_back = len(tl.GetMarkers() or {})
        out = _ok(added=added, by_camera=by_camera, markers_in_timeline=read_back)
        if failed:
            out["failed"] = failed
            out["warning"] = (
                f"{len(failed)} marker(s) could not be placed (tried both the "
                "relative and the absolute frame). See failed."
            )
        return out

    if action == "sort_to_bins":
        recursive = bool(p.get("recursive", True))
        wanted = p.get("folder_name")
        prefix_filter = p.get("prefix")

        # locate the folder to sort within (default: media-pool root)
        target_folder = None
        root = mp.GetRootFolder()
        if wanted:
            def _walk(f):
                if f.GetName() == wanted:
                    return f
                for sub in (f.GetSubFolderList() or []):
                    hit = _walk(sub)
                    if hit:
                        return hit
                return None
            target_folder = _walk(root)
            if not target_folder:
                return _err(f"No media pool folder named '{wanted}'.")
        else:
            target_folder = root

        # collect clips
        clips = []
        def _collect(f):
            clips.extend(f.GetClipList() or [])
            if recursive:
                for sub in (f.GetSubFolderList() or []):
                    _collect(sub)
        _collect(target_folder)
        if prefix_filter:
            clips = [c for c in clips if c.GetName().lower().startswith(prefix_filter.lower())]
        if not clips:
            return _ok(moved=0, bins={}, note=f"No clips found in '{target_folder.GetName()}'.")

        # group by camera
        groups = {}
        skipped = []
        for c in clips:
            cam_name, _col = _camera_of(c.GetName())
            if cam_name:
                groups.setdefault(cam_name, []).append(c)
            else:
                skipped.append(c.GetName())

        # create/find a bin per camera. AddSubFolder lives on MediaPool.
        add_sub = getattr(mp, "AddSubFolder", None)
        if add_sub is None:
            return _err("This build does not expose MediaPool.AddSubFolder.")
        existing = {f.GetName(): f for f in (target_folder.GetSubFolderList() or [])}

        moved, bins, failures = {}, {}, []
        for cam_name, items in groups.items():
            bin_name = p.get("bin_prefix", "") + cam_name
            folder = existing.get(bin_name)
            if folder is None:
                try:
                    folder = add_sub(target_folder, bin_name)
                except Exception as exc:
                    failures.append(f"{bin_name}: {exc}")
                    continue
                if not folder:
                    failures.append(f"{bin_name}: AddSubFolder returned nothing")
                    continue
                existing[bin_name] = folder
            # MoveClips is on the MediaPool proxy, not on the folder.
            try:
                ok = mp.MoveClips(items, folder)
            except Exception as exc:
                failures.append(f"{bin_name}: {exc}")
                continue
            if not ok:
                failures.append(f"{bin_name}: MoveClips returned False")
                continue
            # verify by reading the bin back rather than trusting the return
            landed = len(folder.GetClipList() or [])
            if landed < len(items):
                failures.append(
                    f"{bin_name}: MoveClips reported success but the bin holds "
                    f"{landed} of {len(items)} clips")
            moved[cam_name] = len(items)
            bins[bin_name] = landed

        out = _ok(moved=moved, bins=bins,
                  total=sum(moved.values()),
                  source=target_folder.GetName())
        if skipped:
            out["skipped"] = skipped
        if failures:
            out["failed"] = failures
            out["warning"] = f"{len(failures)} bin(s) reported a problem."
        return out

    if action == "build_timeline":
        import re as _re

        tl_name = p.get("name") or "Camera Comparison"
        want_cams = p.get("cameras")
        gap = int(p.get("scene_gap_frames", 0) or 0)
        sync_at = int(p.get("sync_at", 0) or 0)

        root = mp.GetRootFolder()
        found = []
        def _collect(f):
            found.extend(f.GetClipList() or [])
            for sub in (f.GetSubFolderList() or []):
                _collect(sub)
        _collect(root)
        if not found:
            return _err("No clips in the media pool to build a timeline from.")

        # camera -> scene number -> clip. The naming convention is
        # <prefix><scene>, e.g. ace1/go1/luna2/x3.
        plan = {}
        ignored = []
        for c in found:
            name = c.GetName()
            cam_name, _col = _camera_of(name)
            if not cam_name or (want_cams and cam_name not in want_cams):
                ignored.append(name)
                continue
            m = _re.match(r"^[a-z_]+?(\d+)", name.lower())
            scene = int(m.group(1)) if m else 1
            plan.setdefault(cam_name, {}).setdefault(scene, []).append(c)

        if not plan:
            return _err(
                "No clips matched the camera convention. The names must start "
                "with ace/go/luna/x/vid_ (see the prefix table)."
            )

        # order cameras longest prefix first so the tracks are deterministic
        order = [c for c in ("Insta360 AcePro", "Insta360 Go Ultra",
                             "Insta360 Luna Ultra", "Insta360 X5", "Handy")
                 if c in plan]
        scenes = sorted({s for cam in plan.values() for s in cam})
        if len(order) > 2:
            tl = mp.CreateEmptyTimeline(tl_name)
            if not tl:
                return _err(f"Could not create timeline '{tl_name}' (name in use?).")
            proj.SetCurrentTimeline(tl)
            tl = proj.GetCurrentTimeline()
            # ensure a video track per camera: a new timeline ships with one.
            for _ in range(len(order) - 1):
                tl.AddTrack("video")
        else:
            tl = mp.CreateEmptyTimeline(tl_name)
            if not tl:
                return _err(f"Could not create timeline '{tl_name}' (name in use?).")
            proj.SetCurrentTimeline(tl)
            tl = proj.GetCurrentTimeline()

        placed, by_camera = 0, {}
        skipped_clips = []
        for scene in scenes:
            # The longest clip of the scene decides the slot length.
            scene_clips = [c for cam in order if scene in plan.get(cam, {})
                           for c in plan[cam][scene]]
            if not scene_clips:
                continue
            slot = 1
            for c in scene_clips:
                try:
                    slot = max(slot, int(c.GetClipProperty("Frames") or 1))
                except Exception:
                    pass
            record = sync_at
            for track_idx, cam in enumerate(order, start=1):
                for c in plan.get(cam, {}).get(scene, []):
                    # No endFrame: Resolve then uses the whole clip. Passing one
                    # breaks single-frame media — with Frames=1 the natural
                    # endFrame is 0, and AppendToTimeline(0..0) returns None
                    # (measured; omitting the key places the clip fine).
                    placed_ok = mp.AppendToTimeline([{
                        "mediaPoolItem": c,
                        "startFrame": 0,
                        "trackIndex": track_idx,
                        "recordFrame": record,
                    }])
                    if placed_ok:
                        placed += 1
                        by_camera[cam] = by_camera.get(cam, 0) + 1
                    else:
                        skipped_clips.append(
                            f"{c.GetName()} (track {track_idx}, frame {record})")
            sync_at = record + slot + gap

        out = _ok(timeline=tl.GetName(), placed=placed, by_camera=by_camera,
                  tracks=len(order), scenes=len(scenes))
        if ignored:
            out["ignored"] = ignored[:20]
            out["ignored_count"] = len(ignored)
        if skipped_clips:
            out["not_placed"] = skipped_clips[:20]
            out["warning"] = (
                f"{len(skipped_clips)} clip(s) could not be placed — "
                "AppendToTimeline returned nothing for them."
            )
        return out

    return _err(
        f"Unknown action '{action}'. Use detect, grid_2x2, split_h, split_v, "
        "layout, fullframe, markers, sort_to_bins, build_timeline or read."
    )


if __name__ == "__main__":
    sys.exit(main())
