"""resolve-ext — DaVinci Resolve MCP extension server.

Fills the 21.1.2 gaps that samuelgursky/davinci-resolve-mcp v4.18.2 does not
cover: clip effects, effect properties, attribute copying, and (in later
releases) clip repositioning and frame export.

Lives OUTSIDE the upstream checkout on purpose: `git pull` there can never
overwrite this. It talks to Resolve through the same external scripting API.

Run:
    python server.py            # stdio MCP server
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

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


# --- photo album + node graph helpers (Resolve 21.1.2) -------------------

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

    probes = {
        "Resolve.GetEffectsList": hasattr(app, "GetEffectsList"),
        "TimelineItem.AddEffect": False,
        "TimelineItem.CopyAttributes": False,
    }
    if tl:
        items = tl.GetItemListInTrack("video", 1) or []
        if items:
            it = items[0]
            probes["TimelineItem.AddEffect"] = hasattr(it, "AddEffect")
            probes["TimelineItem.CopyAttributes"] = hasattr(it, "CopyAttributes")
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
      delete_gaps() — DeleteGaps reports success but moves nothing (verified
        twice). The action says so instead of pretending.

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
            return _err(
                f"DeleteGaps returned {ok!r} but NOTHING moved — the items still "
                f"start at {[s for _, s in after]}. MEASURED on Resolve "
                "21.1.2.10: DeleteGaps reports success while leaving the "
                "timeline untouched (tested with clips at frames 0 and 200 and "
                "again at 0/200/400, gaps present). It is a silent no-op on "
                "this build; do not trust its return value. Close gaps in the "
                "Edit page instead."
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
        — Timeline.ExportFrame. **BROKEN on Resolve 21.1.2.10** — it returns
          'frameOffset is out of range for the timeline' for every offset
          tried (0, 5, 100, 200, 216000, 216010), while the same frames export
          fine through 'item'. The action reports this instead of failing
          silently; use 'item' or 'media'.

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
            return _err(
                f"Timeline.ExportFrame(frameOffset={off}) failed: "
                f"{res.get('error')}. MEASURED on Resolve 21.1.2.10: this call "
                "returns 'frameOffset is out of range for the timeline' for "
                "EVERY offset tried (0, 5, 100, 200, 216000, 216010) on a "
                "timeline whose items start at frame 0. The timeline reports "
                "StartTimecode 01:00:00:00 with StartFrame 86400, which looks "
                "like the underlying cause. Treat Timeline.ExportFrame as "
                "BROKEN on this build. Use action='item' (verified working) or "
                "action='media' instead."
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


if __name__ == "__main__":
    mcp.run()
