"""Camera-comparison test: does the grid actually position clips?"""
import glob
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import server as S

import DaVinciResolveScript as dvr

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def show(label, r, n=230):
    print(f"  {label}: {json.dumps(r, default=str)[:n]}")
    return r


# --- build four clips whose names follow the camera convention ------------
tmp = os.path.join(tempfile.gettempdir(), "rc_ext_cams")
os.makedirs(tmp, exist_ok=True)
src_imgs = sorted(glob.glob(os.path.join(os.path.expanduser("~"), "Pictures", "*.png")))[:4]
if len(src_imgs) < 4:
    raise SystemExit("Need 4 source images in ~/Pictures.")
names = ["ace1.mp4.png", "go1.mp4.png", "luna1.mp4.png", "x1.mp4.png"]
made = []
for s, n in zip(src_imgs, names):
    d = os.path.join(tmp, n)
    shutil.copyfile(s, d)
    made.append(d)
print("Testmedien:", [os.path.basename(m) for m in made])

# --- detect() unit check without Resolve ---------------------------------
print("\n=== Kamera-Erkennung (reine Funktion) ===")
cases = [
    ("ace1.mp4", ("Insta360 AcePro", "Orange")),
    ("ACE_2026.mov", ("Insta360 AcePro", "Orange")),
    ("go2.mp4", ("Insta360 Go Ultra", "Green")),
    ("luna1.mp4", ("Insta360 Luna Ultra", "Cyan")),
    ("x1.mp4", ("Insta360 X5", "Blue")),
    ("x5_wide.mp4", ("Insta360 X5", "Blue")),
    ("VID_20260614_170228.mp4", ("Handy", "Gray")),
    ("random.mov", (None, None)),
]
for name, want in cases:
    got = S._camera_of(name)
    check(f"_camera_of({name!r}) -> {want[0]}", got == want, str(got))

# --- live test ------------------------------------------------------------
app = dvr.scriptapp("Resolve")
pm = app.GetProjectManager()
cur = pm.GetCurrentProject()
if cur:
    pm.CloseProject(cur)
for n in list(pm.GetProjectListInCurrentFolder() or []):
    if n.startswith("ZZ_"):
        pm.DeleteProject(n)
proj = pm.CreateProject("ZZ_Cam") or pm.GetCurrentProject()
mp = proj.GetMediaPool()
items = mp.ImportMedia(made)
tl = mp.CreateEmptyTimeline("TLCam")
proj.SetCurrentTimeline(tl)
tl = proj.GetCurrentTimeline()
mp.AppendToTimeline([{"mediaPoolItem": i, "trackIndex": 1, "recordFrame": idx * 200}
                     for idx, i in enumerate(items)])
v1 = tl.GetItemListInTrack("video", 1) or []
print(f"\nTimeline mit {len(v1)} Clips auf V1")

r = show("detect", S.camera_comparison("detect", {}), 420)
check("detect erkennt 4 Kameras", r.get("count") == 4, f"count={r.get('count')}")
check("keine unbekannten Clips", not r.get("unknown"), str(r.get("unknown")))

r = show("read (vorher)", S.camera_comparison("read", {}), 200)
before = {c["name"]: c for c in (r.get("clips") or [])}
sample = list(before.values())[0] if before else {}
check("vorher Zoom = 1.0", sample.get("zoom_x") == 1.0, str(sample.get("zoom_x")))
check("vorher Pan = 0.0", sample.get("pan") == 0.0, str(sample.get("pan")))

print("\n=== grid_2x2 ===")
r = show("grid_2x2", S.camera_comparison("grid_2x2", {}), 400)
check("grid_2x2 angewendet auf 4 Clips", r.get("count") == 4, str(r.get("count")))
check("kein Fehler-Warnhinweis", "warning" not in r, str(r.get("warning"))[:90])
res = r.get("resolution") or [0, 0]
check("Auflösung gelesen", res[0] > 0, str(res))

r = show("read (nachher)", S.camera_comparison("read", {}), 420)
after = {c["name"]: c for c in (r.get("clips") or [])}
ace = next((c for k, c in after.items() if "ace" in k.lower()), {})
check("AcePro Zoom ist 0.5", ace.get("zoom_x") == 0.5, str(ace.get("zoom_x")))
check("AcePro Pan ist -25% (links)",
      ace.get("pan") == -res[0] * 0.25, f"{ace.get('pan')} (erwartet {-res[0]*0.25})")
check("AcePro Tilt ist +25% (oben)",
      ace.get("tilt") == res[1] * 0.25, f"{ace.get('tilt')} (erwartet {res[1]*0.25})")
go = next((c for k, c in after.items() if "go" in k.lower()), {})
check("Go Ultra Pan ist +25% (rechts)", go.get("pan") == res[0] * 0.25, str(go.get("pan")))
luna = next((c for k, c in after.items() if "luna" in k.lower()), {})
check("Luna Tilt ist -25% (unten)", luna.get("tilt") == -res[1] * 0.25, str(luna.get("tilt")))

print("\n=== Kontrolle: die NUTZER-Keys schlagen fehl (Dokumentation) ===")
it = v1[0]
setr = it.SetProperty("PositionX", -100.0)
gotr = it.GetProperty("PositionX")
check("PositionX liefert False (der Bug)", setr is False and gotr is False,
      f"Set={setr!r} Get={gotr!r}")

print("\n=== split_h ===")
r = show("split_h", S.camera_comparison("split_h", {"scale": 0.45}), 260)
check("split_h angewendet", r.get("count") == 4, str(r.get("count")))

print("\n=== layout (explizit) ===")
aid = v1[0].GetUniqueId()
r = show("layout", S.camera_comparison("layout",
        {"assignments": {aid: {"x": 0.0, "y": 0.0, "scale": 0.4}}}), 300)
check("layout wendet an", r.get("applied") == 1, str(r.get("applied")))
check("layout setzt Zoom auf 0.4 wirklich",
      v1[0].GetProperty("ZoomX") == 0.4, str(v1[0].GetProperty("ZoomX")))

print("\n=== fullframe ===")
r = show("fullframe (alle vier)", S.camera_comparison("fullframe",
        {"clip_ids": [i.GetUniqueId() for i in v1]}), 260)
check("fullframe setzt zurueck", r.get("count") == 4, str(r.get("count")))
check("Zoom ist wieder 1.0", v1[0].GetProperty("ZoomX") == 1.0,
      str(v1[0].GetProperty("ZoomX")))
check("Pan ist wieder 0.0", v1[0].GetProperty("Pan") == 0.0,
      str(v1[0].GetProperty("Pan")))
r = show("fullframe ohne Ziel (muss verweigern)", S.camera_comparison("fullframe", {}))
check("fullframe ohne Ziel verweigert", "error" in r, str(r.get("error"))[:60])

print("\n=== markers ===")
r = show("markers", S.camera_comparison("markers", {}), 340)
# Gemessen: der Marker auf dem Clip bei Timeline-Position 0 laesst sich nicht
# setzen (weder relativ noch absolut). Erwartet: die uebrigen landen, der
# Fehlschlag wird GEMELDET und der Readback stimmt mit der Meldung ueberein.
check("Marker gesetzt (mindestens 3 von 4)", (r.get("added") or 0) >= 3,
      f"added={r.get('added')} failed={r.get('failed')}")
check("gescheiterter Marker wird gemeldet",
      bool(r.get("failed")) and bool(r.get("warning")),
      str(r.get("warning"))[:70])
mk = tl.GetMarkers() or {}
check("READBACK stimmt mit der gemeldeten Zahl (kein Fake)",
      len(mk) == r.get("added"),
      f"{len(mk)} in Timeline, {r.get('added')} gemeldet")
names = [v.get("name") for v in mk.values() if isinstance(v, dict)]
check("Marker tragen Kamera-Namen", all(n in names for n in
      ("Insta360 Go Ultra", "Insta360 Luna Ultra", "Insta360 X5")), str(names))

print("\n=== Aufraeumen ===")
pm.CloseProject(proj)
check("Testprojekt geloescht", bool(pm.DeleteProject("ZZ_Cam")))
leftover = [p for p in (pm.GetProjectListInCurrentFolder() or []) if p.startswith("ZZ_")]
check("keine ZZ_-Reste", not leftover, str(leftover))
shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{'='*62}\nPASS: {len(PASS)}   FAIL: {len(FAIL)}")
for f in FAIL:
    print("   -", f)
print("=" * 62)
sys.exit(1 if FAIL else 0)
