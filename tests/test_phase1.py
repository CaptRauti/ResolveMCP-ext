"""Phase-1 test: photo_albums + node_graph, against live Resolve.

Assertions check that values CHANGED and can be READ BACK, and that known-broken
API calls report their failure honestly instead of pretending to work.
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import server as S

import DaVinciResolveScript as dvr

MEDIA_GLOB = os.environ.get(
    "RESOLVE_EXT_TEST_MEDIA",
    os.path.join(os.path.expanduser("~"), "Pictures", "*.png"),
)

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def show(label, r, n=200):
    print(f"  {label}: {json.dumps(r, default=str)[:n]}")
    return r


app = dvr.scriptapp("Resolve")
pm = app.GetProjectManager()
cur = pm.GetCurrentProject()
if cur:
    pm.CloseProject(cur)
if "ZZ_Phase1" in (pm.GetProjectListInCurrentFolder() or []):
    pm.DeleteProject("ZZ_Phase1")
proj = pm.CreateProject("ZZ_Phase1") or pm.GetCurrentProject()
mp = proj.GetMediaPool()
imgs = sorted(glob.glob(MEDIA_GLOB))[:4]
if len(imgs) < 4:
    raise SystemExit(f"Need 4 images matching {MEDIA_GLOB!r}. Set RESOLVE_EXT_TEST_MEDIA.")
items = mp.ImportMedia(imgs)
clip_ids = [i.GetUniqueId() for i in items]
print(f"\nSetup: {len(items)} Medien in {proj.GetName()}")

# ============================ ALBUM LIFECYCLE ============================
print("\n=== photo_albums: Lifecycle ===")
r = show("list (leer)", S.photo_albums("list", {}))
check("leere Liste", r.get("count") == 0)

r = show("create", S.photo_albums("create", {"name": "P1"}))
album_id = (r.get("album") or {}).get("id")
check("create liefert Album mit id", bool(album_id), str(album_id))

r = show("current nach create", S.photo_albums("current", {}))
check("create setzt das Album als current", (r.get("album") or {}).get("id") == album_id,
      str(r.get("album")))

r = show("create_from_photos (der zuverlaessige Weg)",
         S.photo_albums("create_from_photos", {"name": "P1b", "clip_ids": clip_ids}))
check("create_from_photos liefert Album", bool(r.get("album")), str(r.get("album")))
check("Album enthaelt 4 Fotos", (r.get("album") or {}).get("photo_count") == 4,
      f"photo_count={(r.get('album') or {}).get('photo_count')}")

r = show("list", S.photo_albums("list", {}))
check("2 Alben vorhanden", r.get("count") == 2, str(r.get("count")))

r = show("photos", S.photo_albums("photos", {"name": "P1b"}))
photos = r.get("photos") or []
check("photos listet 4", len(photos) == 4, str(len(photos)))
p0 = photos[0] if photos else {}
check("Photo hat id + rating", bool(p0.get("id")) and p0.get("rating") is not None, str(p0))

r = show("quick_export_presets", S.photo_albums("quick_export_presets", {}))
check("Quick-Export-Presets lesbar", isinstance(r.get("presets"), list) and r.get("presets"),
      str(r.get("presets")))

# ============================ BROKEN: add_photos ============================
print("\n=== add_photos: MUSS den Defekt melden ===")
r = show("add_photos", S.photo_albums("add_photos", {"name": "P1", "clip_ids": clip_ids}), 320)
check("add_photos meldet den Defekt ehrlich",
      "error" in r and "BROKEN" in r["error"], str(r.get("error"))[:110])
r2 = show("photos in P1 danach", S.photo_albums("photos", {"name": "P1"}))
check("add_photos hat wirklich nichts hinzugefuegt", (r2.get("count") or 0) == 0,
      str(r2.get("count")))

# ============================ PER-PHOTO ============================
print("\n=== photo_albums: Bewertung (scharf) ===")
r = show("rate 4", S.photo_albums("rate", {"photo_id": p0.get("id"), "name": "P1b", "stars": 4}))
check("rate setzt 4", r.get("rating") == 4, str(r.get("rating")))
r = show("photo (frisch gelesen)", S.photo_albums("photo", {"photo_id": p0.get("id"), "name": "P1b"}))
check("Rating ist PERSISTENT", (r.get("photo") or {}).get("rating") == 4,
      str((r.get("photo") or {}).get("rating")))

print("\n=== photo_albums: Versionen ===")
r = show("versions", S.photo_albums("versions", {"photo_id": p0.get("id"), "name": "P1b"}))
v_before = len(r.get("versions") or [])
check("Versionen lesbar", v_before >= 1, str(r.get("versions")))
r = show("add_version", S.photo_albums("add_version",
        {"photo_id": p0.get("id"), "name": "P1b", "version_name": "P1V2"}))
check("Version hinzugefuegt", len(r.get("versions") or []) > v_before, str(r.get("versions")))

print("\n=== photo_albums: Flags ===")
r = show("flag Blue", S.photo_albums("flag",
        {"photo_id": p0.get("id"), "name": "P1b", "color": "Blue"}))
check("Flag gesetzt", "Blue" in (r.get("flags") or []), str(r.get("flags")))
r = show("flag clear", S.photo_albums("flag",
        {"photo_id": p0.get("id"), "name": "P1b", "clear": True}))
check("Flag geloescht", not (r.get("flags") or []), str(r.get("flags")))

print("\n=== photo_albums: Fusion-Comp auf Foto ===")
r = show("fusion_comps vorher", S.photo_albums("fusion_comps", {"photo_id": p0.get("id"), "name": "P1b"}))
n_before = r.get("count") or 0
r = show("fusion_add", S.photo_albums("fusion_add", {"photo_id": p0.get("id"), "name": "P1b"}))
check("Fusion-Comp hinzugefuegt", (r.get("count") or 0) > n_before, f"{n_before} -> {r.get('count')}")

print("\n=== photo_albums: Effekte / Stills / remove ===")
r = show("effects_list", S.photo_albums("effects_list", {"photo_id": p0.get("id"), "name": "P1b"}))
check("effects_list laeuft", "error" not in r, str(r.get("count")))
r = show("stills", S.photo_albums("stills", {"name": "P1b"}))
check("GrabStill laeuft", "error" not in r, str(r.get("grabbed")))
r = show("remove_photos", S.photo_albums("remove_photos",
        {"name": "P1b", "photo_ids": [p0.get("id")]}))
check("Foto entfernt", r.get("removed") == 1, f"removed={r.get('removed')} remaining={r.get('remaining')}")

print("\n=== photo_albums: rename / delete ===")
r = show("rename", S.photo_albums("rename", {"album_id": album_id, "new_name": "P1renamed"}))
check("rename ok", (r.get("album") or {}).get("name") == "P1renamed", str(r.get("album")))
r = show("delete alle", S.photo_albums("delete", {}))
check("beide Alben geloescht", r.get("deleted") == 2, str(r.get("names")))
r = show("list danach", S.photo_albums("list", {}))
check("Liste leer", r.get("count") == 0)

# ============================ NODE GRAPH ============================
print("\n=== node_graph: Timeline-Clip ===")
tl = mp.CreateEmptyTimeline("TLP1")
proj.SetCurrentTimeline(tl)
tl = proj.GetCurrentTimeline()
mp.AppendToTimeline([{"mediaPoolItem": items[0], "trackIndex": 1, "recordFrame": 0}])
v1 = tl.GetItemListInTrack("video", 1) or []
check("Clip auf V1", len(v1) == 1)
iid = v1[0].GetUniqueId() if v1 else None

r = show("info", S.node_graph("info", {"item_id": iid}), 260)
check("info liefert num_nodes", (r.get("num_nodes") or 0) >= 1, str(r.get("num_nodes")))

r = show("label setzen", S.node_graph("label", {"item_id": iid, "node_index": 1, "label": "P1Node"}))
check("label ok", "error" not in r)
r = show("info nachher", S.node_graph("info", {"item_id": iid}), 260)
labels = [n.get("label") for n in (r.get("nodes") or [])]
check("Label PERSISTENT", "P1Node" in labels, str(labels))

r = show("color Teal", S.node_graph("color", {"item_id": iid, "node_index": 1, "color": "Teal"}))
check("color ok", "error" not in r)
r = show("info nach color", S.node_graph("info", {"item_id": iid}), 260)
colors = [n.get("color") for n in (r.get("nodes") or [])]
check("Farbe PERSISTENT", "Teal" in colors, str(colors))

r = show("enable False", S.node_graph("enable", {"item_id": iid, "node_index": 1, "enabled": False}))
check("enable False ok", "error" not in r)
r = show("enable True", S.node_graph("enable", {"item_id": iid, "node_index": 1, "enabled": True}))
check("enable True ok", "error" not in r)

r = show("color leeren", S.node_graph("color", {"item_id": iid, "node_index": 1, "color": ""}))
check("leerer String loescht die Farbe", "error" not in r)
r = show("info nach clear", S.node_graph("info", {"item_id": iid}), 260)
check("Farbe wirklich weg", all(not n.get("color") for n in (r.get("nodes") or [])),
      str([n.get("color") for n in (r.get("nodes") or [])]))

print("\n=== node_graph: Fehlerpfade + bekannte Defekte ===")
r = show("ungueltiger node_index", S.node_graph("label",
        {"item_id": iid, "node_index": 999, "label": "x"}))
check("node_index 999 abgelehnt", "error" in r and "1..1" in r["error"], str(r.get("error"))[:70])

r = show("ungueltige Farbe", S.node_graph("color",
        {"item_id": iid, "node_index": 1, "color": "NeonPink"}))
check("Farbe NeonPink abgelehnt", "error" in r)

r = show("reset_grades ohne confirm", S.node_graph("reset_grades", {"item_id": iid}))
check("reset_grades verlangt confirm", "error" in r and "confirm" in r["error"])

r = show("reset_colors (Timeline-Graph)", S.node_graph("reset_colors", {"item_id": iid}))
check("reset_colors meldet Fehlen ehrlich auf Timeline-Graph",
      "error" in r and ("not available" in r["error"] or "missing" in r["error"]),
      str(r.get("error"))[:90])

r = show("info via clip_id (bekannt defekt)", S.node_graph("info", {"clip_id": clip_ids[0]}), 220)
check("clip_id meldet den Defekt ehrlich",
      "error" in r and "not callable" in r["error"], str(r.get("error"))[:90])

print("\n=== Aufraeumen ===")
pm.CloseProject(proj)
deleted = pm.DeleteProject("ZZ_Phase1")
check("Testprojekt geloescht", bool(deleted))
leftover = [p for p in (pm.GetProjectListInCurrentFolder() or []) if p.startswith("ZZ_")]
check("keine ZZ_-Reste", not leftover, str(leftover))

print(f"\n{'='*62}\nPASS: {len(PASS)}   FAIL: {len(FAIL)}")
if FAIL:
    print("Fehlgeschlagen:")
    for f in FAIL:
        print("   -", f)
print("=" * 62)
sys.exit(1 if FAIL else 0)
