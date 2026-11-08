# AGENTS.md

Instructions for AI agents installing or working on this project.
See [README.md](README.md) for the human-facing documentation.

---

## What this is

`resolve-ext` is an MCP server that adds DaVinci Resolve scripting surfaces the
other Resolve MCP servers do not implement. It is a **companion**, not a
replacement: it runs alongside the others without overlap.

Ten tools, one entry point, pure Python. No compiled parts.

### The Resolve MCP landscape — three servers, no overlap

Before installing anything, understand that Resolve is covered by three
independent servers that do different jobs. A user who wants **full coverage
needs all three**; installing one and finding a capability missing is the usual
disappointment.

| Server | Where it comes from | Tools | What it is for |
|---|---|---|---|
| **Blackmagic's own** (`ResolveMCP.exe`) | **Ships with DaVinci Resolve 21** — nothing to download | 14 | A *meta-server*: it hands the agent Resolve's scripting-API stubs and a Python sandbox (`run_script`, `search_scripting_api`, `get_whats_new`), plus LUT/DCTL management. It writes no Resolve actions itself. |
| **community** (`samuelgursky/davinci-resolve-mcp`) | npm or git | 37 (390 with `--full`) | The workhorse: granular tools for editing, media pool, render, markers, grading, Fusion. Plus a second `davinci-resolve-advanced` server (18 Node tools) for source-safe media analysis. |
| **this project** (`resolve-ext`) | pip | 10 | The gaps the other two leave: clip effects and their properties, Paste Attributes, frame export, photo albums, node-graph labelling, and the multi-camera comparison layouts. |

They coexist. All three talk to the same Resolve through the same scripting API,
which is **single-client** — so register them together, but know they share one
Resolve.

Do not install one and present it as the whole picture. If the user asks for
"the Resolve MCP", ask which of these they mean, or install all three.

---

## Full setup — install all three

Do these in order. Steps 1 and 2 are independent; step 3 assumes step 2 exists,
because `resolve-ext` is a companion.

### Server 1 — Blackmagic's own: nothing to install

It is already on disk wherever DaVinci Resolve 21 is installed. Just register it:

| Platform | Path to the server |
|---|---|
| Windows | `%ProgramFiles%\Blackmagic Design\DaVinci Resolve\ResolveMCP.exe` |
| macOS | `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Applications/ResolveMCP` |
| macOS (App Store build) | `/Applications/DaVinci Resolve Studio.app/Contents/Applications/ResolveMCP` |
| Linux | `/opt/resolve/bin/ResolveMCP` |

```json
{
  "mcpServers": {
    "bmd-native": {
      "command": "C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\ResolveMCP.exe"
    }
  }
}
```

On Windows the installer lets the user choose any directory — including another
drive — so `%ProgramFiles%` is only a guess. Do not hard-code it. Either query
the real location, or set the override the server itself honours:

```bash
# Ask Windows where Resolve actually lives (the .drp file association):
reg query "HKCR\ResolveDrpFile\shell\open\command" /ve
# → (Default) REG_SZ "D:\Blackmagic Design\DaVinci Resolve\Resolve.exe" "%1"
```

Rounding that value up to its directory and appending `ResolveMCP.exe` gives
the real path. `RESOLVE_MCP_PATH` overrides everything if the user wants it
elsewhere.

Verify before registering — the binary has its own CLI:

```bash
"<path>/ResolveMCP.exe" --dump-tools      # prints its tool definitions and exits
"<path>/ResolveMCP.exe" --test            # performs an init handshake and exits
```

**Do not read a `Traceback ... ImportError: DLL load failed while importing
fusionscript` as "broken".** That is the server failing to find Resolve's
library; it says nothing about the installation. `--dump-tools` works
regardless, and the server connects normally when launched from a client with a
normal environment. On Windows, `%ProgramFiles%` and the file-association check
above are the reliable way to the binary.

**Claude Desktop users have a shortcut:** Blackmagic also ships
`DaVinciResolve.mcpb` in the same directory. That is an MCP bundle — opening it
installs and configures the server for Claude Desktop in one step. It is a Node
wrapper (needs Node ≥18) that spawns the same binary lazily. Prefer it over
hand-editing the config when the client supports bundles.

### Server 2 — the community server

```bash
npx davinci-resolve-mcp setup
```

The npm package is a bootstrapper: it finds Resolve, creates a managed virtual
environment, and can configure the client itself. For a checkout instead:

```bash
git clone https://github.com/samuelgursky/davinci-resolve-mcp.git
cd davinci-resolve-mcp
python install.py --clients manual        # print the config, write nothing
```

**When driving this non-interactively, always use `--clients manual` or
`--dry-run`.** Bare `install.py` prompts, and a prompt inside an agent run
hangs. Useful flags: `--clients <id,id|all|manual>`, `--dry-run`, `--no-venv`,
`--server`, `--python`, `--update-policy never`.

`--clients manual` prints working config for *this* machine, including the
second `davinci-resolve-advanced` server. Register what it prints rather than
composing the entry by hand.

Note the installer's own warning: a Python newer than 3.12 may fail to connect
(`scriptapp("Resolve")` returns `None`). If that happens, install Python 3.10–3.12
and re-run against it.

### Server 3 — this project

See **Install — the whole procedure** below. Short version:

```bash
pip install https://github.com/CaptRauti/ResolveMCP-ext/releases/download/v1.0.0/resolve_ext-1.0.0-py3-none-any.whl
resolve-ext doctor        # exit 0 before you register it
```

### Finally — check all three are live

Reload the client's MCP connections, then confirm the tools from each are
present. The three name-spaces are distinguishable at a glance:

- from this project — `resolve_ext_status`, `camera_comparison`, `node_graph`, …
- from the community server — `timeline`, `media_pool`, `project`, …
- from Blackmagic — `run_script`, `search_scripting_api`, `get_whats_new`, …

If a whole group is missing, that server is not registered — not a bug in the
others.

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
`/reload-mcp`). Then confirm all fifteen tools are present:

`camera_comparison`, `clip_attrs`, `clip_position`, `clone_media`, `cdl`,
`effects`, `export_frame`, `folder_ops`, `jobs`, `node_graph`, `photo_albums`,
`project_extras`, `resolve_ext_status`, `thumbnails`, `auto_color`

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
| Blackmagic server: `ImportError: DLL load failed while importing fusionscript` | It cannot find Resolve's library in that environment | Not a broken install — `--dump-tools` still works and it connects from a client. Check the path is right and Resolve is running |
| Blackmagic server: no tools at all in the client | `%ProgramFiles%` was assumed, but Resolve is on another drive | Resolve the real path via `HKCR\ResolveDrpFile\shell\open\command`, or set `RESOLVE_MCP_PATH` |
| Community server: connects but `scriptapp("Resolve")` returns `None` | Python newer than 3.12 | Install Python 3.10–3.12 and re-run `install.py` with `--python` |
| Community `install.py` never returns | It is prompting | Never call it bare; use `--clients manual` or `--dry-run` |
| Only some of the three servers' tools are present | That is normal until all three are registered | They are separate servers; see "Full setup" |

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
