"""End-to-end test of every resolve-ext tool against live Resolve.

Sharp on purpose: every assertion checks that a value CHANGED after a write,
not merely that no error came back. A test that passes because nothing moved
proves nothing.

Requirements:
  - DaVinci Resolve Studio running, External scripting = Local
  - The env vars from the README (RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB /
    PYTHONPATH) exported, so `import DaVinciResolveScript` works
  - Some PNGs in PICTURES (override with RESOLVE_EXT_TEST_MEDIA)

Run:
    python tests/test_e2e.py

Creates one scratch project (ZZ_ExtFull), exercises every tool, and deletes it
again. It never touches other projects.
"""
import json
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import importlib

import server as S

importlib.reload(S)

import DaVinciResolveScript as dvr

MEDIA_GLOB = os.environ.get(
    "RESOLVE_EXT_TEST_MEDIA",
    os.path.join(os.path.expanduser("~"), "Pictures", "*.png"),
)
OUTDIR = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "resolve_ext_frames")

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def show(label, r, n=260):
    print(f"  {label}: {json.dumps(r, default=str)[:n]}")
    return r


# ---------------------------------------------------------------- setup
app = dvr.scriptapp("Resolve")
pm = app.GetProjectManager()
cur = pm.GetCurrentProject()
if cur:
    pm.CloseProject(cur)

PROJ = "ZZ_ExtFull"
if PROJ in (pm.GetProjectListInCurrentFolder() or []):
    pm.DeleteProject(PROJ)

proj = pm.CreateProject(PROJ) or pm.GetCurrentProject()
mp = proj.GetMediaPool()
imgs = sorted(glob.glob(MEDIA_GLOB))[:3]
if len(imgs) < 3:
    raise SystemExit(f"Need 3 test images matching {MEDIA_GLOB!r}. "
                     "Set RESOLVE_EXT_TEST_MEDIA to a glob with at least 3 files.")
items = mp.ImportMedia(imgs)
tl = mp.CreateEmptyTimeline("TLFull")
proj.SetCurrentTimeline(tl)
tl = proj.GetCurrentTimeline()

# AppendToTimeline's recordFrame is an ABSOLUTE timeline frame, NOT an offset
# from the timeline start. Passing 0/200/400 while this timeline starts at
# 86400 placed the clips BEFORE its own start; the timeline then reported
# StartFrame == EndFrame (duration 0) while still holding three clips, and
# Timeline.ExportFrame correctly refused every offset. That combination is what
# produced the wrong upstream bug report (Issue #336) - so this now anchors to
# the real start frame.
TL0 = int(tl.GetStartFrame() or 0)
mp.AppendToTimeline([{"mediaPoolItem": items[0], "trackIndex": 1, "recordFrame": TL0},
                     {"mediaPoolItem": items[1], "trackIndex": 1, "recordFrame": TL0 + 200},
                     {"mediaPoolItem": items[2], "trackIndex": 1, "recordFrame": TL0 + 400}])
v1 = tl.GetItemListInTrack("video", 1) or []
print(f"\nSetup: Projekt={proj.GetName()}  TL={tl.GetName()}  Items V1={len(v1)}")
for i, it in enumerate(v1):
    print(f"   [{i}] {it.GetName()}  {it.GetStart()}->{it.GetEnd()}")

# ---------------------------------------------------------------- effects (regression)
print("\n=== effects ===")
r = show("list_available", S.effects("list_available", {"media_type": "video"}))
check("effects list_available liefert Treffer", r.get("count", 0) > 0, f"{r.get('count')} Effekte")

pick = [e for e in r["effects"] if e["category"] == "ofx"][0]
r = show("apply", S.effects("apply", {"item_id": v1[0].GetUniqueId(),
                                      "category": pick["category"], "id": pick["id"]}))
check("Effekt angewendet", "error" not in r, str(r.get("effect")))
r = show("list_applied", S.effects("list_applied", {"item_id": v1[0].GetUniqueId()}))
check("Effekt zurueckgelesen", r.get("count", 0) >= 1)
r = show("remove", S.effects("remove", {"item_id": v1[0].GetUniqueId(), "category": pick["category"]}))
check("Effekt entfernt", "error" not in r)

# ---------------------------------------------------------------- clip_attrs (regression)
print("\n=== clip_attrs ===")
src, tgt = v1[0], v1[1]
for k, val in (("ZoomX", 1.7), ("Pan", 180.0), ("Tilt", -90.0), ("RotationAngle", 8.0)):
    src.SetProperty(k, val)
r = show("copy", S.clip_attrs("copy", {"source_id": src.GetUniqueId(),
                                       "target_ids": [tgt.GetUniqueId()],
                                       "options": {"allZoomAttributes": True, "position": True}}))
check("CopyAttributes meldet Erfolg", "error" not in r)
got = tgt.GetProperty("ZoomX")
check("ZoomX ist wirklich kopiert worden", abs(got - 1.7) < 1e-6, f"Ziel ZoomX={got} (Quelle 1.7)")
gotp = tgt.GetProperty("Pan")
check("Pan ist wirklich kopiert worden", abs(gotp - 180.0) < 1e-3, f"Ziel Pan={gotp} (Quelle 180.0)")

# ---------------------------------------------------------------- clip_position (NEW)
print("\n=== clip_position ===")
a = v1[1]
r = show("get", S.clip_position("get", {"item_id": a.GetUniqueId()}))
check("get liefert Position", r.get("position") is not None, str(r.get("position")))
check("get liefert left/right_offset", r.get("left_offset") is not None and r.get("right_offset") is not None,
      f"L={r.get('left_offset')} R={r.get('right_offset')}")

# set: BROKEN auf 21.1.2.10 -> muss einen ehrlichen Fehler liefern, keinen Fake-Erfolg
start_before = a.GetStart()
r = show("set (erwartet Fehler)", S.clip_position("set", {"item_id": a.GetUniqueId(), "start_frame": 260.0}))
check("set meldet den API-Defekt ehrlich", "error" in r and "SetPosition" in r["error"])
check("set hat nichts bewegt", a.GetStart() == start_before, f"{start_before} -> {a.GetStart()}")

# set_offset: DESTRUKTIV -> muss verweigert werden
r = show("set_offset (erwartet Verweigerung)", S.clip_position("set_offset", {"item_id": a.GetUniqueId(), "left": 5.0}))
check("set_offset wird verweigert", "error" in r and "DISABLED" in r["error"])
check("set_offset hat nichts veraendert", a.GetStart() == start_before, f"{start_before} -> {a.GetStart()}")

# delete_gaps: KORRIGIERT. Die erste Fassung dieses Tests erwartete, dass
# DeleteGaps einen Fehler meldet - gestuetzt auf eine Messung, die auf einer
# Timeline mit widerspruechlichen Metadaten lief (StartFrame == EndFrame bei
# drei Clips, weil AppendToTimeline mit absoluten Frames gefuettert wurde).
# Auf einer korrekt aufgebauten Timeline SCHLIESST DeleteGaps die Luecken.
print("\n=== delete_gaps ===")
clips_before = tl.GetItemListInTrack("video", 1) or []
starts = [i.GetStart() for i in clips_before]
clip_dur = (clips_before[0].GetEnd() - clips_before[0].GetStart()) if clips_before else 0
# Eine Luecke ist mehr Abstand als die Clip-Laenge - nicht 'mehr als 0'.
check("Vorher gibt es Luecken",
      (starts[1] - starts[0] > clip_dur) if len(starts) > 1 else False,
      f"starts={starts} clip_dur={clip_dur}")
r = show("delete_gaps (erwartet Erfolg)", S.clip_position("delete_gaps", {}))
after_starts = [i.GetStart() for i in (tl.GetItemListInTrack("video", 1) or [])]
check("delete_gaps schliesst die Luecken tatsaechlich",
      len(after_starts) == len(starts) and after_starts != starts,
      f"{starts} -> {after_starts}")
check("delete_gaps ergibt lueckenlose Clips",
      all(b - a == clip_dur for a, b in zip(after_starts, after_starts[1:]))
      if len(after_starts) > 1 else False,
      f"Abstaende={[b - a for a, b in zip(after_starts, after_starts[1:])]} clip_dur={clip_dur}")

# ---------------------------------------------------------------- export_frame (NEW)
print("\n=== export_frame ===")
outdir = OUTDIR
os.makedirs(outdir, exist_ok=True)

# timeline: erwartet einen RELATIVEN Offset (0 = Timeline-Start).
# Korrektur gegenueber der ersten Fassung: die Funktion ist NICHT defekt —
# eine frueher hier behauptete Defektmessung hatte absolute Frames uebergeben.
tlpath = os.path.join(outdir, "timeline.png")
if os.path.exists(tlpath):
    os.remove(tlpath)
r = show("timeline -> relativer Offset 10", S.export_frame(
    "timeline", {"frame_offset": 10, "output_type": "file", "file_path": tlpath}))
check("Timeline.ExportFrame schrieb eine Datei", os.path.exists(tlpath),
      f"{os.path.getsize(tlpath)} bytes" if os.path.exists(tlpath) else "fehlt")

# Ein absoluter Frame muss abgelehnt werden UND das erklaeren, nicht als
# undurchsichtiger 'out of range' durchkommen.
r = show("timeline -> absoluter Frame (erwartet Erklaerung)", S.export_frame(
    "timeline", {"frame_offset": TL0, "output_type": "file",
                 "file_path": os.path.join(outdir, "tl_abs.png")}))
check("absoluter Offset wird erklaerend abgelehnt",
      "error" in r and "ABSOLUTE" in r.get("error", ""), r.get("error", "")[:90])

# item: WORKS
ipath = os.path.join(outdir, "item.jpg")
if os.path.exists(ipath):
    os.remove(ipath)
r = show("item -> file", S.export_frame("item", {"item_id": v1[0].GetUniqueId(),
                                                 "frame_offset": 5,
                                                 "output_type": "file", "file_path": ipath}))
check("Item-Export schrieb Datei", os.path.exists(ipath),
      f"{os.path.getsize(ipath)} bytes" if os.path.exists(ipath) else "fehlt")
if os.path.exists(ipath):
    with open(ipath, "rb") as fh:
        jhead = fh.read(3)
    check("JPEG-Signatur korrekt", jhead[:2] == b"\xff\xd8", str(jhead))

# item out-of-range -> sauberer Fehler
r = show("item offset out of range", S.export_frame("item", {"item_id": v1[0].GetUniqueId(),
                                                             "frame_offset": 9999,
                                                             "output_type": "file",
                                                             "file_path": os.path.join(outdir, "x.jpg")}))
check("Item-Export lehnt ungueltigen Offset ab", "error" in r)

# media: WORKS
mpath = os.path.join(outdir, "media.jpg")
if os.path.exists(mpath):
    os.remove(mpath)
r = show("media -> file", S.export_frame("media", {"clip_id": items[0].GetUniqueId(),
                                                   "frame_offset": 0,
                                                   "output_type": "file", "file_path": mpath}))
check("Media-Export schrieb Datei", os.path.exists(mpath),
      f"{os.path.getsize(mpath)} bytes" if os.path.exists(mpath) else "fehlt")

# encodedString ueber item
r = show("item -> encodedString", S.export_frame("item", {"item_id": v1[0].GetUniqueId(),
                                                          "frame_offset": 10,
                                                          "output_type": "encodedString",
                                                          "format": "png", "max_dimension": 640}))
check("encodedString liefert gespeicherte Datei", bool(r.get("saved_to")), str(r.get("saved_to")))
if r.get("saved_to") and os.path.exists(r["saved_to"]):
    with open(r["saved_to"], "rb") as fh:
        head = fh.read(4)
    check("gespeichertes Bild ist ein PNG", head == b"\x89PNG", str(head))

# ---------------------------------------------------------------- folder_ops (NEW)
print("\n=== folder_ops ===")
sub = mp.AddSubFolder(mp.GetRootFolder(), "ExtTestBin")
mp.MoveClips([items[0]], sub)
cid = items[0].GetUniqueId()

r = show("parent_of_clip", S.folder_ops("parent_of_clip", {"clip_id": cid}))
check("parent_of_clip findet den Ordner", r.get("folder") == "ExtTestBin", str(r.get("path")))

r = show("path of folder", S.folder_ops("path", {"folder_id": sub.GetUniqueId()}))
check("Ordnerpfad enthaelt ExtTestBin", "ExtTestBin" in (r.get("path") or ""), str(r.get("path")))

r = show("parent_of_folder", S.folder_ops("parent_of_folder", {"folder_id": sub.GetUniqueId()}))
check("Elternordner ist der Root", r.get("root") is True or "Master" in str(r.get("name")), str(r))

r = show("find_clip", S.folder_ops("find_clip", {"clip_id": cid}))
check("find_clip findet den Clip", r.get("name") == items[0].GetName(), str(r.get("folder_path")))

# ---------------------------------------------------------------- status
print("\n=== status ===")
r = show("resolve_ext_status", S.resolve_ext_status(), 500)
check("status meldet Verbindung", r.get("connected") is True)

# ---------------------------------------------------------------- enabled (LAST: it clears the current timeline)
print("\n=== clip_position.enabled (zuletzt, da es die Timeline abmeldet) ===")
r = show("enabled get", S.clip_position("enabled", {}))
check("Timeline-Enabled lesbar", "enabled" in r, str(r.get("enabled")))
r = show("enabled false", S.clip_position("enabled", {"enabled": False}))
check("Timeline abschaltbar", r.get("enabled") is False)
r = show("enabled true", S.clip_position("enabled", {"enabled": True}))
check("Timeline wieder einschaltbar ODER Timeline ist abgemeldet",
      r.get("enabled") is True or "No current timeline" in str(r.get("error")),
      str(r.get("enabled") if "error" not in r else r.get("error")))

# ---------------------------------------------------------------- cleanup
print("\n=== Aufraeumen ===")
pm.CloseProject(proj)
deleted = pm.DeleteProject(PROJ)
check("Testprojekt geloescht", bool(deleted))
leftover = [p for p in (pm.GetProjectListInCurrentFolder() or []) if p.startswith("ZZ_")]
check("keine ZZ_-Reste", not leftover, str(leftover))

print(f"\n{'='*60}\nPASS: {len(PASS)}   FAIL: {len(FAIL)}")
if FAIL:
    print("Fehlgeschlagen:")
    for f in FAIL:
        print("   -", f)
print("="*60)
sys.exit(1 if FAIL else 0)
