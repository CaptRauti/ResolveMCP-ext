"""Offline checks: everything that can be verified WITHOUT DaVinci Resolve.

This is what runs in CI on Windows, macOS and Linux. The live suites
(test_e2e, test_phase1, test_extras, test_camera) need a running Resolve Studio
and are skipped when it is absent, so a CI failure here always means a real
packaging or import defect rather than a missing application.

Run:
    python tests/test_offline.py
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


print("=== 1. Import ohne Resolve ===")
try:
    import server
    check("server importierbar ohne Resolve-Installation", True)
except Exception as exc:
    check("server importierbar ohne Resolve-Installation", False, f"{type(exc).__name__}: {exc}")
    print(f"\nPASS: {len(PASS)}   FAIL: {len(FAIL)}")
    sys.exit(1)

check("Version ist gesetzt", bool(getattr(server, "__version__", None)),
      str(getattr(server, "__version__", None)))

print("\n=== 2. DaVinciResolveScript wird NICHT beim Import geladen ===")
check("kein Resolve-Import auf Modulebene",
      "DaVinciResolveScript" not in sys.modules,
      "wichtig: sonst schlaegt 'pip install' gefolgt von 'resolve-ext --help' fehl")

print("\n=== 3. Tool-Registrierung ===")
tools = []
try:
    tm = getattr(server.mcp, "_tool_manager", None)
    if tm is not None:
        registered = tm.list_tools()
        tools = [t.name for t in registered]
except Exception as exc:
    print(f"    (Tool-Manager nicht lesbar: {exc})")

if tools:
    expected = {"effects", "clip_attrs", "export_frame", "folder_ops",
                "photo_albums", "node_graph", "project_extras",
                "camera_comparison", "clip_position"}
    missing = expected - set(tools)
    check(f"{len(tools)} Tools registriert", len(tools) >= 9, str(sorted(tools)))
    check("alle erwarteten Tools vorhanden", not missing, f"fehlen: {sorted(missing)}")
else:
    # Fallback: die Dekoratoren im Quelltext zaehlen
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    n = src.count("@mcp.tool()")
    check(f"{n} @mcp.tool-Dekoratoren im Quelltext", n >= 9, str(n))

print("\n=== 4. CLI ===")
import io
from contextlib import redirect_stdout

buf = io.StringIO()
with redirect_stdout(buf):
    rc = server.main(["--version"])
out = buf.getvalue().strip()
check("--version gibt 0 zurueck", rc == 0, f"rc={rc}")
check("--version nennt eine Version", server.__version__ in out, out)

buf = io.StringIO()
with redirect_stdout(buf):
    rc = server.main(["--help"])
check("--help gibt 0 zurueck", rc == 0, f"rc={rc}")
check("--help erklaert 'doctor'", "doctor" in buf.getvalue())

buf = io.StringIO()
with redirect_stdout(buf):
    rc = server.main(["gibtsnicht"])
check("unbekanntes Kommando gibt 2 zurueck", rc == 2, f"rc={rc}")

print("\n=== 5. Plattform-Pfadlogik ===")
paths = server.find_resolve_paths()
check("platform erkannt", paths.get("platform") in
      ("windows", "macos", "linux"), str(paths.get("platform")))
check("api_path gesetzt", bool(paths.get("api_path")), str(paths.get("api_path")))
check("lib_path gesetzt", bool(paths.get("lib_path")), str(paths.get("lib_path")))
check("modules_path haengt an api_path",
      bool(paths.get("modules_path")) and paths["modules_path"].startswith(paths["api_path"]),
      str(paths.get("modules_path")))

plat = paths["platform"]
if plat == "windows":
    check("Windows: api_path unter ProgramData",
          "ProgramData" in (paths["api_path"] or ""), paths["api_path"])
    check("Windows: lib_path ist eine .dll",
          (paths["lib_path"] or "").endswith("fusionscript.dll"), paths["lib_path"])
elif plat == "macos":
    check("macOS: api_path unter /Library/Application Support",
          "/Library/Application Support" in (paths["api_path"] or ""), paths["api_path"])
    check("macOS: lib_path ist eine .so",
          (paths["lib_path"] or "").endswith("fusionscript.so"), paths["lib_path"])
elif plat == "linux":
    check("Linux: api_path unter /opt/resolve",
          (paths["api_path"] or "").startswith("/opt/resolve"), paths["api_path"])
    check("Linux: lib_path ist eine .so",
          (paths["lib_path"] or "").endswith("fusionscript.so"), paths["lib_path"])

print("\n=== 6. Env-Override respektiert ===")
before = dict(os.environ)
try:
    if paths["api_path"] and os.path.isdir(paths["api_path"]):
        os.environ["RESOLVE_SCRIPT_API"] = paths["api_path"]
        p2 = server.find_resolve_paths()
        check("RESOLVE_SCRIPT_API wird uebernommen",
              p2["api_path"] == paths["api_path"], p2["api_path"])
    else:
        check("Env-Override-Test uebersprungen (kein Resolve installiert)", True)
finally:
    os.environ.clear()
    os.environ.update(before)

print("\n=== 7. apply_resolve_env ueberschreibt nichts ===")
sentinel = "/definitely/not/real/xyz"
os.environ["RESOLVE_SCRIPT_API"] = sentinel
try:
    server.apply_resolve_env()
    check("vorhandener RESOLVE_SCRIPT_API bleibt unangetastet",
          os.environ["RESOLVE_SCRIPT_API"] == sentinel,
          os.environ["RESOLVE_SCRIPT_API"])
finally:
    os.environ.pop("RESOLVE_SCRIPT_API", None)

print("\n=== 8. Reine Funktionen (kein Resolve noetig) ===")
for name, want in [("ace1.mp4", ("Insta360 AcePro", "Orange")),
                   ("go2.mov", ("Insta360 Go Ultra", "Green")),
                   ("luna1.mp4", ("Insta360 Luna Ultra", "Cyan")),
                   ("x5.mp4", ("Insta360 X5", "Blue")),
                   ("VID_20260614.mp4", ("Handy", "Gray")),
                   ("unrelated.mov", (None, None))]:
    got = server._camera_of(name)
    check(f"_camera_of({name!r}) -> {want[0]}", got == want, str(got))

print("\n=== 9. Alle Quelldateien parsen ===")
for base, _dirs, files in os.walk(ROOT):
    if ".git" in base or "__pycache__" in base:
        continue
    for f in files:
        if not f.endswith(".py"):
            continue
        fp = os.path.join(base, f)
        rel = os.path.relpath(fp, ROOT)
        try:
            ast.parse(open(fp, encoding="utf-8").read())
            check(f"{rel} syntaktisch ok", True)
        except SyntaxError as exc:
            check(f"{rel} syntaktisch ok", False, f"Zeile {exc.lineno}: {exc.msg}")

print(f"\n{'='*62}\nPASS: {len(PASS)}   FAIL: {len(FAIL)}")
if FAIL:
    print("Fehlgeschlagen:")
    for f in FAIL:
        print("   -", f)
print("=" * 62)
sys.exit(1 if FAIL else 0)
