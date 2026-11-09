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
                "camera_comparison", "clip_position", "thumbnails",
                "auto_color", "cdl", "jobs", "clone_media",
                "resolve_ext_status"}
    missing = expected - set(tools)
    extra = set(tools) - expected
    check(f"{len(tools)} Tools registriert (erwartet {len(expected)})",
          len(tools) == len(expected), str(sorted(tools)))
    check("alle erwarteten Tools vorhanden", not missing, f"fehlen: {sorted(missing)}")
    check("keine unerwarteten Tools", not extra, f"unerwartet: {sorted(extra)}")
else:
    # Fallback: die Dekoratoren im Quelltext zaehlen
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    n = src.count("@mcp.tool()")
    check(f"{n} @mcp.tool-Dekoratoren im Quelltext", n == 15, str(n))

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

print("\n=== 9. Beide MCP-SDK-Generationen (1.x FastMCP / 2.x MCPServer) ===")
# pyproject pins mcp<2, but a user's environment can already carry mcp 2.x,
# and then the pin does not save them: pip only warns. The server must import
# and list its tools on both SDK generations instead of dying with a
# ModuleNotFoundError before it can answer even `--version` or `doctor`.
check("SDK-Generation erkannt", getattr(server, "SDK_MAJOR", 0) in (1, 2),
      f"SDK_MAJOR={getattr(server, 'SDK_MAJOR', None)}")
check("Server-Objekt konstruiert", server.mcp is not None,
      type(server.mcp).__name__ if server.mcp is not None else "None")

# The tool surface is what the client sees, so prove it survives the SDK
# switch by driving a real stdio handshake against a child process.
import json
import subprocess

_child = subprocess.Popen(
    [sys.executable, os.path.join(ROOT, "server.py")],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    text=True, bufsize=1, cwd=ROOT)


def _rpc(obj, want_id):
    """Send one message and wait for its reply (None on EOF).

    The handshake must be interactive. Writing initialize, initialized and
    tools/list as one burst and closing stdin races the shutdown, and the
    tools/list reply is then sometimes lost (measured on mcp 1.30: 2 of 6
    runs). A real client keeps the pipe open and waits per request — that
    form was 6 of 6 on both SDK generations.
    """
    _child.stdin.write(json.dumps(obj) + "\n")
    _child.stdin.flush()
    while True:
        _line = _child.stdout.readline()
        if not _line:
            return None
        try:
            _obj = json.loads(_line)
        except Exception:
            continue
        if _obj.get("id") == want_id:
            return _obj


try:
    _init = _rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "test_offline", "version": "0"}}}, 1)
    _child.stdin.write(json.dumps(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    _child.stdin.flush()
    _list = _rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                  "params": {}}, 2)
    _info = ((_init or {}).get("result") or {}).get("serverInfo") or {}
    _names = sorted(t["name"] for t in
                    ((_list or {}).get("result") or {}).get("tools") or [])
    check("stdio-Handshake antwortet mit serverInfo", bool(_info), str(_info))
    check("serverInfo meldet den Namen ResolveMCP-ext",
          _info.get("name") == "ResolveMCP-ext", str(_info.get("name")))
    check("serverInfo traegt eine Version (nicht leer wie mcp 2.x ohne version=)",
          bool(_info.get("version")), str(_info.get("version")))
    check(f"tools/list liefert 15 Tools (SDK {getattr(server, 'SDK_MAJOR', '?')})",
          len(_names) == 15, str(_names))
except Exception as exc:  # pragma: no cover
    check("stdio-Handshake laeuft", False, f"{type(exc).__name__}: {exc}")
finally:
    _child.kill()


print("\n=== 10. Alle Quelldateien parsen ===")
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
