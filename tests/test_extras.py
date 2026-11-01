"""Test of project_extras: render presets, audio render formats, transcription.

Render presets and transcription are GUI-dependent on 21.1.2.10 (see the tool's
docstring), so those assertions accept either a real result or an honest error —
what they reject is a silent false success.
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

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def show(label, r, n=260):
    print(f"  {label}: {json.dumps(r, default=str)[:n]}")
    return r


app = dvr.scriptapp("Resolve")
pm = app.GetProjectManager()
cur = pm.GetCurrentProject()
if cur:
    pm.CloseProject(cur)
for n in list(pm.GetProjectListInCurrentFolder() or []):
    if n.startswith("ZZ_"):
        pm.DeleteProject(n)
proj = pm.CreateProject("ZZ_Extras") or pm.GetCurrentProject()
mp = proj.GetMediaPool()
imgs = sorted(glob.glob(os.path.join(os.path.expanduser("~"), "Pictures", "*.png")))[:1]
items = mp.ImportMedia(imgs)
cid = items[0].GetUniqueId()
print(f"\nSetup: {proj.GetName()}, Clip {items[0].GetName()}")

print("\n=== capabilities ===")
r = show("capabilities", S.project_extras("capabilities", {}), 500)
check("capabilities laeuft", "surfaces" in r)

print("\n=== Render-Presets ===")
r = show("render_presets", S.project_extras("render_presets", {}))
presets = r.get("presets") or []
check("Preset-Liste nicht leer", len(presets) > 0, f"{len(presets)} Presets")

if presets:
    name = presets[0]
    # Factory-Presets: UpdateRenderPreset gibt False. Das ist erwartet und wird gemeldet.
    r = show(f"update_render_preset('{name}')", S.project_extras("update_render_preset", {"preset_name": name}))
    check("update_render_preset gibt Ergebnis oder ehrlichen Fehler",
          "error" in r or r.get("preset") == name,
          str(r.get("preset") if "error" not in r else r["error"])[:70])
    r = show("update_render_preset (unbekannt)", S.project_extras("update_render_preset", {"preset_name": "DoesNotExist_ZZZ"}))
    check("unbekanntes Preset wird abgelehnt", "error" in r and "returned False" in r["error"],
          str(r.get("error"))[:70])
    r = show("quick_export_enable true", S.project_extras("quick_export_enable",
            {"preset_name": name, "enabled": True}))
    check("quick_export_enable gibt Ergebnis oder ehrlichen Fehler",
          "error" in r or r.get("quick_export") is True,
          str(r.get("quick_export") if "error" not in r else r["error"])[:70])

print("\n=== Audio-Formate ===")
r = show("audio_formats", S.project_extras("audio_formats", {}), 400)
formats = r.get("formats") or {}
check("Audio-Formate nicht leer", len(formats) > 0, f"{len(formats)} Formate")
if formats:
    ext = list(formats.values())[0]
    r = show(f"audio_codecs('{ext}')", S.project_extras("audio_codecs", {"format_extension": ext}))
    check("Audio-Codecs nicht leer", len(r.get("codecs") or {}) > 0, str(r.get("codecs")))
r = show("audio_codecs ungueltig", S.project_extras("audio_codecs", {"format_extension": "zzz"}))
check("ungueltige Extension abgelehnt", "error" in r)

print("\n=== Transcription ===")
r = show("transcription (leer)", S.project_extras("transcription", {"clip_id": cid}))
check("transcription laeuft", "error" not in r, str(r.get("transcription") is None))

# SetTranscription versuchen — Timecodes innerhalb des Clips
tr = {
    "language": "de",
    "segments": [
        {"start": "01:00:00:00", "end": "01:00:01:00", "text": "Hallo Welt"},
    ],
}
r = show("set_transcription", S.project_extras("set_transcription", {"clip_id": cid, "transcription": tr}), 400)
check("set_transcription meldet Ergebnis ODER ehrlichen Fehler",
      "error" in r or "verified" in r,
      str(r.get("verified") if "error" not in r else r["error"])[:80])

# Validierung: leere Segmente
r = show("set_transcription ohne segments", S.project_extras("set_transcription",
        {"clip_id": cid, "transcription": {"language": "de"}}))
check("fehlende segments abgelehnt", "error" in r)
r = show("set_transcription mit kaputtem Segment", S.project_extras("set_transcription",
        {"clip_id": cid, "transcription": {"language": "de", "segments": [{"start": "x"}]}}))
check("unvollstaendiges Segment abgelehnt", "error" in r and "start, end and text" in r["error"])

print("\n=== Aufraeumen ===")
pm.CloseProject(proj)
print("geloescht:", pm.DeleteProject("ZZ_Extras"))
print("Reste:", [p for p in (pm.GetProjectListInCurrentFolder() or []) if p.startswith("ZZ_")])

print(f"\n{'='*60}\nPASS: {len(PASS)}   FAIL: {len(FAIL)}")
for f in FAIL:
    print("   -", f)
print("="*60)
