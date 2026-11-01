# AGENTS.md

Instructions for AI agents installing or working on this project.
See [README.md](README.md) for the human-facing documentation.

---

## What this is

`resolve-ext` is an MCP server that adds DaVinci Resolve scripting surfaces the
mainstream Resolve MCP servers do not implement. It is a **companion** server,
not a replacement: it runs alongside another Resolve MCP server without
overlap, so install it *in addition to* whatever the user already has.

Ten tools, one entry point, pure Python. No compiled parts.

---

## Install — the whole procedure

### Step 0 — Confirm the prerequisites before doing anything

Three things must be true. Check them, do not assume:

1. **DaVinci Resolve Studio is installed.** External scripting is a Studio
   feature. The free build refuses the connection, and no amount of
   configuration will change that. If the user has the free version, stop and
   tell them — do not proceed.
2. **Python 3.10 or newer** is available:
   ```bash
   python3 --version   # or: python --version
   ```
3. **Resolve is running** with external scripting enabled:
   **Preferences → System → General → External scripting using → Local**.
   The setting is invisible until Resolve is launched at least once, so if the
   user has never opened it, ask them to start it before continuing.

### Step 1 — Install the package

Prefer a released wheel over a git checkout; it is versioned and installs
without a build step.

```bash
# The version in the filename must match the release tag.
pip install https://github.com/CaptRauti/ResolveMCP-ext/releases/download/v1.0.0/resolve_ext-1.0.0-py3-none-any.whl
```

Or from git:

```bash
pip install git+https://github.com/CaptRauti/ResolveMCP-ext
```

The wheel is pure Python and platform-independent — **the same file installs
on Windows, macOS and Linux.** Do not look for a platform-specific build;
there isn't one and there does not need to be.

If `pip` is not on PATH, use `python3 -m pip`. If the machine refuses to
install into the system Python (PEP 668, "externally-managed-environment"),
install into the interpreter the MCP client will use, or use `pipx`:

```bash
pipx install https://github.com/CaptRauti/ResolveMCP-ext/releases/download/v1.0.0/resolve_ext-1.0.0-py3-none-any.whl
```

### Step 2 — Verify, and believe only the exit code

```bash
resolve-ext doctor
```

This checks the Python version, locates Resolve's scripting API for the
platform it is running on, tests the import, and opens a live connection.

**Exit `0` means it works. Anything else means it does not — read the output
before continuing.** `doctor` names the exact missing path and what to enable,
so pass that message to the user rather than paraphrasing it.

Do not register a server you have not seen pass `doctor`. A broken server
registered into a client fails silently and looks like the client's bug.

### Step 3 — Register with the MCP client

The server finds Resolve's scripting API by itself. On a default installation
**there is nothing to configure**:

```json
{
  "mcpServers": {
    "resolve-ext": {
      "command": "resolve-ext"
    }
  }
}
```

For the explicit form — or when Resolve lives somewhere non-standard — run:

```bash
resolve-ext env
```

It prints the configuration **for the machine it runs on**, as generic JSON and
as a `hermes mcp add` command, including the exact `RESOLVE_SCRIPT_API`,
`RESOLVE_SCRIPT_LIB` and `PYTHONPATH` values.

Use that output. Do not construct the paths yourself and do not copy paths from
the README — the paths are platform-specific and the README quotes one
platform's examples.

**When editing a client config, add the server entry flat under the client's
existing `mcpServers` key.** Do not introduce a second `mcpServers` level: that
nesting is silently ignored by most clients and the tools never appear.

### Step 4 — Confirm the tools are visible

After registering, the client must reload its MCP connections (in Hermes:
`/reload-mcp`). Then confirm all ten tools are present:

`camera_comparison`, `clip_attrs`, `clip_position`, `effects`, `export_frame`,
`folder_ops`, `node_graph`, `photo_albums`, `project_extras`,
`resolve_ext_status`

If fewer appear, the registration is wrong — not the server. Re-run
`resolve-ext doctor` first.

---

## Troubleshooting — symptom to cause

| Symptom | Cause | Fix |
|---|---|---|
| `doctor` says the API folder is missing | Resolve is not installed, or is the free build | Install Resolve **Studio** |
| `doctor` finds the paths but the connection fails | Resolve is not running, or external scripting is off | Start Resolve; Preferences → System → General → External scripting using → Local |
| `DaVinciResolveScript does not import` | Wrong Python, or a stale `RESOLVE_SCRIPT_API` pointing nowhere | The server ignores a variable that points to a missing path; check the value it reports and unset it if stale |
| `pip install` fails with `externally-managed-environment` | PEP 668 | venv, or `pipx` |
| `ModuleNotFoundError: server` after install | Older release | Reinstall from `v1.0.0` or later |
| Tools do not appear in the client after registering | Nested `mcpServers`, or the client was not reloaded | Flatten the config; reload MCP connections |
| `mcp` 2.x import error | An unpinned `mcp` | The pin `<2` ships in the package metadata; reinstall the package rather than upgrading `mcp` |

Resolve's scripting API is **single-client**: only one instance of Resolve can
serve it at a time. Two MCP servers can both be registered, but they talk to
the same Resolve.

---

## Working on this repository

```bash
git clone https://github.com/CaptRauti/ResolveMCP-ext
cd ResolveMCP-ext
pip install .
python tests/test_offline.py     # 30 assertions, no Resolve needed
```

`tests/test_offline.py` is the only suite that runs without Resolve and is what
CI runs. It deliberately verifies that `server.py` imports **with Resolve
absent** — otherwise `pip install` followed by `resolve-ext --help` would break
for anyone without Resolve. Keep that property.

The live suites need a running Resolve Studio and real media:

```bash
python tests/test_e2e.py      # core tools
python tests/test_phase1.py   # photo albums + node graph
python tests/test_extras.py   # render presets, audio, transcription
python tests/test_camera.py   # camera layouts, labels, sorting
```

### Layout

- `server.py` — the entire server: platform detection, the `doctor` and `env`
  commands, and all ten tools. One file on purpose; it is a companion server,
  not a framework.
- `tests/` — the suites above.
- `README.md` — install, tool reference, and the measured API behaviour.
- `CHANGELOG.md` — per release, including which Resolve API calls are broken.

### Conventions that matter

- **Verify against a live Resolve, never against the documentation.** Several
  documented API calls return `True` while doing nothing or while corrupting
  the timeline. `CHANGELOG.md` lists the ones measured so far, with values.
- **Never expose a destructive call as a working action.** Where an API is
  broken, the tool returns a failure carrying the measurement, rather than
  reporting a success the user would trust.
- **A `True` return proves nothing.** Read the value back and check it.
- **Do not duplicate another server's surface.** If the upstream server covers
  a capability, this project does not re-implement it. That is the whole reason
  it exists as an extension rather than a fork.
- Comments and documentation in English, since the repository is public.
- Test projects are the user's real work: clean up anything you create.
