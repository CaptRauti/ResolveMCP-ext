# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.2] — 2026-11-23

### Fixed

- **A bad numeric parameter no longer kills the tool call with a traceback.**
  Every tool read frame and track numbers as `int(p.get("track_index", 1))`.
  A model that sends `{"track_index": "1"}` was fine, but `"one"`, `""`, `true`
  or `[1]` raised `ValueError: invalid literal for int()` from inside the tool —
  the caller got a transport error and no message. Measured on the previous
  release against a connected project: `clip_position(action="get",
  params={"track_index": "one"})` → `ValueError`. The same call now answers
  `{"error": "Parameter 'track_index' must be a number, got 'one'. Send it as a
  JSON number or a numeric string."}`
- **`params` that is not an object is refused up front.** `params=[]` or
  `params="x"` used to fail on the first `p.get` with `AttributeError`; it now
  returns an error naming the expected shape.
- **`track_index` below 1 and an unknown `track_type` are refused instead of
  silently addressing nothing.** `track_index: 0` reached
  `GetItemListInTrack("video", 0)`, which returns an empty list — that reads
  like "the clip is gone", not "you addressed track 0". `track_type: "Video"`
  (capitalised) was accepted and matched no track at all.
- **All 19 tools validate before touching Resolve** through one shared
  `_check_params` / `_num` pair, so the message is identical everywhere and no
  action can bypass it. `resolve_ext_status` stays exempt — it is the diagnostic
  that must answer without a connection.

### Tests

- `tests/test_offline.py` §10b drives **every tool through its real signature**
  with 216 hostile parameter combinations and asserts that none of them raises.
  This is the blind spot that hid the 1.1.1 defect: the suite called tools
  directly and never on the path a foreign caller takes.

## [1.1.1] — 2026-11-22

### Fixed

- **`resolve_ext_status` now takes `action`/`params` like every other tool.**
  It was declared `resolve_ext_status()` while the other 18 tools carry the
  `(action, params)` house shape, so a caller that drives tools generically died
  with `TypeError: resolve_ext_status() got an unexpected keyword argument
  'action'`. Both parameters are optional and ignored; `resolve_ext_status()`,
  `resolve_ext_status("status", {})` and `resolve_ext_status(action=None,
  params={...})` return the identical dict (measured on 21.2.0.6). Nothing that
  worked before stops working. Reported on Paperclip [RAU-154] by the agent
  that hit it during a verification run, which is exactly the kind of
  inconsistency a green offline suite cannot catch: the tests call the function
  directly, not through the generic path.

## [1.1.0] — 2026-11-22

Four tools for the last gaps against the 21.2 type stub. Every one of them
measured live on Resolve Studio 21.2.0.6 (Windows) by calling it and reading
the result back — including the failures, which are reported as failures.

### Added

- **`project_presets`** — the project-settings preset lifecycle
  (`SaveCurrentProjectSettingsAsNewPreset`, `UpdateProjectSettingsPreset`,
  `SetProjectSettingsPreset`, `DeleteProjectSettingsPreset`). The mainstream
  server could only list them. Save/apply/update/delete round-tripped against
  the real list. **Defaults to dry run**, because upstream issue #207 documents
  this exact sequence destroying a never-saved project's `Sm2MultiSysData`
  table while every call returned `True`. Measured here: `pf.SaveProject` is
  not callable on 21.2 (SaveProject lives on **ProjectManager**), so the
  "save first" advice is applied through `pm.SaveProject` instead.
- **`multicam`** — `info` and `smart_switch`. Two findings that a stub cannot
  tell you: `PerformMulticamSmartSwitch` is on the **TimelineItem**, not on the
  Timeline (Timeline: not callable, Item: answers), and a multicam item is
  identified **only by its name** (`<clip> - Angle 1`) — there is no
  `GetIsMulticamClip` on this build. A single-angle multicam clip answers
  `False`; that is the API, not the tool.
- **`render_preset_admin`** — `list` and `create` (`SaveAsNewRenderPreset`),
  verified by re-listing the presets (37 factory presets before, 38 with the
  new one, back to 37 after `DeleteRenderPreset`). `DeleteRenderPreset` exists
  even though `ViewRenderPresetList`-style neighbours do not appear in the stub;
  the tool uses it for cleanup and reports when it is absent.
- **`keyboard_presets`** — `list`, `current`, `load`, `export`, `import_file`,
  `delete`. Only the first three work on 21.2.0.6: loading 'Adobe Premiere Pro'
  changed the current preset and stayed changed; `ExportKeyboardPreset` and
  `ImportKeyboardPreset` returned `False` for every path and extension tried,
  including a byte-for-byte copy of Resolve's own `keyboard.preset.xml`, and
  `DeleteKeyboardPreset` answered `False` with the list unchanged. Each action
  carries `supported`, so "this build cannot" never reads as "I used it wrong".

### Not a gap (checked, not built)

- **No `DeleteRenderPreset` in the stub** was assumed — wrongly. The call
  exists and works; the assumption came from grepping for fewer spellings than
  the API uses. Call first, then conclude.

## [1.0.6] — 2026-11-22

### Fixed

- **A cached Resolve handle that answers `None` is now dropped, not served.**
  Resolve's proxy dies with its process in two shapes, and only one of them
  raises. The documented shape leaves every method slot as `None`, so a call
  raises `TypeError: 'NoneType' object is not callable`. The quiet shape — seen
  after a restart — succeeds and returns `None`. v1.0.3 validated the cache by
  *calling* a method and treating "no exception" as "alive", which cached the
  quiet corpse forever: every tool then answered with a `None`-derived failure
  until the process was killed by hand, even though a fresh `scriptapp()` would
  have connected. The check is now the **return value**: `_is_live(app)` requires
  a truthy `GetProductName()`, and `_connect()` refuses to cache a handle that
  fails it — both for the cache read and for a fresh connection, since a
  connected-but-mute app is no more usable than an absent one.

  Covered offline in `tests/test_offline.py` §10 against three stand-in proxies
  (quiet-dead, raising-dead, live). Mutation-checked: restoring the old
  "no exception means alive" logic fails exactly the two quiet-dead assertions
  (`nicht zurueckgegeben`, `nicht gecacht`) and nothing else. Not verified
  against a live Resolve restart — the run that shipped this had no Resolve
  instance; the live evidence for the quiet shape is the session finding behind
  the v1.0.3 note.

## [1.0.5] — 2026-11-09

### Fixed

- **The server now runs on mcp 2.x as well as 1.x.** mcp 2.0 renamed the SDK's
  server class: `from mcp.server.fastmcp import FastMCP` raised a bare
  `ModuleNotFoundError`. Because that import sits at module level, it took the
  whole file down — `resolve-ext --version` and `resolve-ext doctor` failed too,
  i.e. exactly the two commands a user reaches for to find out what is wrong.
  The import now tries `mcp.server.mcpserver.MCPServer` first and falls back to
  `mcp.server.fastmcp.FastMCP`, exposing the generation as `server.SDK_MAJOR`.

  The `mcp[cli]>=1.30,<2` pin stays (v1 is the supported line and the pin is
  still the right default), but a pin does not protect a user whose environment
  already carries mcp 2.x: pip only *warns* on the conflict. Measured against
  **mcp 2.3.0**: 15 tools registered and listed over stdio, a real
  `resolve_ext_status` call returned the live connection
  (`DaVinci Resolve Studio 21.2.0.6`, project `MCP_212_Tools`), and `doctor`
  passed end to end. The 15 tools use only the surface the SDK's own migration
  guide lists as unchanged (`@mcp.tool()` with the same handler signatures,
  plain dict returns, `mcp.run()` for stdio) — so this is a two-line import,
  not a port.

- **`serverInfo` carries the server version again on mcp 2.x.** v2 reports an
  empty version unless it is passed to the constructor; it is now passed.

### Added

- **Offline suite section 9** — asserts the SDK generation was detected,
  constructs the server object, and drives a real stdio `initialize` +
  `tools/list` handshake against a child process, checking `serverInfo` and the
  15 tool names. Runs on whichever SDK is installed, so the suite can be run
  once per generation.
- **CI job `sdk2`** — installs the package with `mcp[cli]>=2,<3`, runs the CLI
  and the full offline suite against it, so the dual import cannot regress.

## [1.0.4] — 2026-11-09

### Added

- **`clip_position` → `j_l_cut`** — the J-cut / L-cut primitive, and the reason
  this tool grew. It shifts ONLY the audio of a linked clip relative to its
  picture, via `Timeline.MoveItems(..., moveLinkedItems=False)`, so the picture
  stays put and the pair stays linked with the offset intact. Negative
  `offset_frames` starts the audio earlier (J-cut — the sound leads the image),
  positive starts it later (L-cut — the sound outlasts it). Verified: an L-cut of
  +24 moved the audio 86400 → 86424; a real J-cut of −12 on a clip with a
  predecessor moved its audio 86496 → 86484, with Resolve trimming the
  predecessor's audio tail to make room — exactly what a J-cut does in the NLE.
- **`clip_position` → `set_offset`** now works, and covers `SetRightOffset` —
  which neither this project nor the mainstream server exposed. It sets the head
  or tail TRIM (`left=n` begins the clip `n` frames into its source). Measured on
  a clip at 86400 with source 0–71: `left=5` → start 86405 / source_start 5 /
  duration 67, and `left=0` restored it exactly. Fully reversible.
- **`clip_position` → `set` / `move`** move clips again and return before/after
  readbacks.

### Fixed

- **Three of this project's own claims were wrong and are withdrawn.**
  `SetPosition`, `Timeline.MoveItems` and `SetLeftOffset` were documented as
  broken or destructive, and `set_offset` was disabled outright with a lecture
  about a bug that does not exist. All three work on 21.2.0.6. The destructive
  reading came from a timeline whose `StartFrame == EndFrame` (duration 0) while
  still holding clips — the `AppendToTimeline` trap already documented below. The
  tool was refusing to do things that work; reported upstream as issue #336.

### Notes

- Two traps `j_l_cut` now names in its error messages instead of leaving the
  caller to guess: a clip appended with `mediaType=1` lands as **video only**
  (nothing to offset — append without `mediaType`), and a J-cut needs a
  **predecessor**, because Resolve refuses to place a clip before the timeline's
  `StartFrame`.
- `Timeline.SetClipsLinked([videoItem], True)` returns `True` and **silently
  fails** to rejoin a pair — it needs both items. `j_l_cut` therefore never
  unlinks; `moveLinkedItems=False` is what holds the picture still.

## [1.0.3] — 2026-11-08

### Added

**DaVinci Resolve 21.2 coverage — the complete 21.2 scripting delta — plus the
two 21.1 surfaces no server covered.** Five new tools plus new options and
actions on three existing ones. Every claim below was verified on Resolve
Studio 21.2.0.6 with a real call *and* a readback, not from the type stubs:

- **`thumbnails`** — `ExportThumbnails` on a timeline item, the timeline, a
  media-pool item or a photo album: renders the frames you name into one
  labelled grid image, to file or as an encoded string, and returns the sheet
  geometry. `file_path` needs an image extension; frames may carry their own
  labels.
- **`auto_color`** — `ApplyAutoColor` / `GetAutoColorEnabled` /
  `SetAutoColorEnabled` / `ClearAutoColor`, on a timeline clip **and** on a
  photo album item (`target="photo"`). The Color page must be showing — on Edit
  the identical calls return `False` and change nothing — so the tool switches
  to Color itself and reports `page_switched_from`.
- **`cdl`** — `GetCDL` / `SetCDL`, likewise on a clip or a photo. A set/read
  round-trip returns exactly the values written. `GetCDL` needs the node index.
  **SetCDL needs all four keys** — a partial dict returns `False` and changes
  nothing (measured: slope alone, slope+offset, slope+offset+power all failed) —
  so the tool reads the current CDL and overlays what you passed. Color page
  required.
- **`export_frame`** — `roi_x`/`roi_y`/`roi_width`/`roi_height` (normalised,
  0..1) and `quality`. A region of interest renders a cropped still without a
  render pass: `roi 0.25/0.25/0.5/0.5` with `max_dimension=512` returns 512x288.
- **`node_graph`** — `info` now reports each node's `enabled` flag via
  `Graph.GetNodeEnabled` (21.2). On an older build the call fails and the key is
  omitted rather than reported as a false `False`.
- **`project_extras`** — `playback_frame_rate` / `set_playback_frame_rate`
  (`Project.SetSetting('timelinePlaybackFrameRate')`, verified: set '25', read
  back '25') and the Extras Download Manager: `extras_list`, `extras_install`,
  `extras_uninstall`.
- **`jobs`** (new tool) — the non-blocking job status getters 21.1 introduced:
  `GetTranscribeAudioStatus`, `GetAnalyzeForSlateStatus`,
  `GetSmartReframeStatus`, `GetDetectSceneCutsStatus`,
  `GetCreateSubtitlesFromAudioStatus`, `GetRenderWithQuickExportStatus`, plus
  `GetRenderJobStatus`. Neither server exposed any of them, so a queued
  analysis could never be polled. Verified: all six answer on 21.2.0.6.
- **`clone_media`** (new tool) — the MediaStorage Clone Tool:
  `StartCloneMedia` / `StopCloneMedia` / `GetCloneStatus` /
  `SetCloneToolSettings`. Zero coverage upstream. Verified end-to-end: a source
  file was queued, copied, and a checksum manifest landed beside it.
  **Windows gotcha:** Resolve rejects forward-slash paths here — it returns
  `False` and copies nothing; the tool normalises them.

The mainstream server (4.19.3) covers none of these — `ExportThumbnails`,
`ApplyAutoColor`, the extras manager and the ROI options score zero hits in its
source, and its `api_truth` table still records `timelinePlaybackFrameRate` as
returning False for every value form and `Graph.SetNodeEnabled` as write-only
with no `GetNodeEnabled`. Both are wrong for 21.2: measured working here.

### Fixed

**The server looked broken after a Resolve restart.** `_connect()` cached the
Resolve app handle forever, but Resolve's proxy dies with the Resolve process —
after a restart every call on the cached handle raised
`'NoneType' object is not callable`, so even `resolve_ext_status` failed until
the MCP server itself was restarted. The cache is now validated with a cheap
call and dropped when stale, so the server reconnects on its own.

### Notes

- `ImportMedia` with a path that does not exist hangs the scripting call on 21.2
  (the project is created, then the call blocks until the client times out) and
  leaves Resolve's scripting socket wedged until Resolve is restarted. Check
  paths before importing.

## [1.0.2] — 2026-11-06

### Fixed

**`resolve_ext_status` reported `TimelineItem.AddEffect` and
`TimelineItem.CopyAttributes` as `false` with no clip selected, and probed the
timeline with `hasattr()`.** Proxies make every attribute check pass, so the
probe proved nothing. It now calls the methods it reports, which is the only
reliable test on a proxy object (see "The Proxy Trap" in the README):

- `Resolve.GetEffectsList` — called
- `Timeline.GetItemListInTrack` — called on video track 1; `null` when no
  timeline is open
- `TimelineItem.GetProperty` / `GetFusionCompCount` — only when the track holds
  an item, because they need a clip

The old entries are gone rather than kept as placeholders: a surface that was
never called should not be reported at all.

## [1.0.1] — 2026-11-01

### Fixed

**Three calls were documented as broken on the strength of a bad measurement.**
All three were re-measured on the same build, Resolve Studio 21.1.2.10, and all
three work.

The root cause was the test setup, not the API. `AppendToTimeline`'s
`recordFrame` is an **absolute** timeline frame, not an offset from the timeline
start. The harness fed it `0/200/400` on a timeline starting at `86400`, so the
clips landed outside the timeline's own range and the timeline reported
`StartFrame == EndFrame` (duration 0) while holding three clips. Every
timeline-relative call then behaved as if the timeline were empty.

- **`Timeline.ExportFrame`** — works. `frameOffset` is relative to the timeline
  start, valid `0..duration-1`; offsets 0..479 succeed on a 480-frame timeline
  and 480 is refused. An absolute frame is always refused, which reads like a
  failure. The action now explains that instead of reporting a defect.
- **`Timeline.DeleteGaps`** — works. Verified `[86400, 86600, 86800]` →
  `[86400, 86520, 86640]`, gaps closed. It does nothing only on a timeline whose
  metadata contradicts its contents, and the error now says so.
- **`Timeline.AddMarker`** — works at relative frame 0. The call that returns
  `True` and writes nothing is `TimelineItem.AddMarker` on the clip at timeline
  position 0, verified by reading `tl.GetMarkers()` back. Markers are placed
  through the timeline, never through the item.

### Added

- `AppendToTimeline` accepting a `recordFrame` below `GetStartFrame()` is now
  documented as a silent footgun, with the symptom it produces.
- The `export_frame` timeline action detects an absolute offset and names the
  relative one it should have been.

### Changed

- `tests/test_e2e.py` anchors its `recordFrame` values to the real start frame,
  and the `delete_gaps` and `timeline` export assertions now check that the call
  **works** rather than that it fails.

Reported upstream in [issue #336][336] with the correction attached.

[336]: https://github.com/samuelgursky/davinci-resolve-mcp/issues/336

## [1.0.0] — 2026-11-01

First release. Nine MCP tools covering DaVinci Resolve scripting surfaces the
mainstream Resolve MCP servers do not implement, plus a self-configuring
installer.

### Added

- **`effects`** — clip effects and their properties: `Resolve.GetEffectsList`,
  `TimelineItem.AddEffect` / `GetEffects` / `DeleteEffects`, `Effect.GetInfo` /
  `Get|SetIsEnabled` / `Get|SetIndex`. Measured 36 Fusion + 98 OFX effects on a
  stock Resolve Studio 21.1.2.10.
- **`clip_attrs`** — `TimelineItem.CopyAttributes`, the API behind Edit-page
  Paste Attributes. 36 options in 6 groups.
- **`export_frame`** — `TimelineItem.ExportFrame` and
  `MediaPoolItem.ExportFrame`, to file or base64.
- **`folder_ops`** — `MediaPoolItem` / `Folder.GetParentFolder` with a
  recursive media-pool walk.
- **`photo_albums`** — the whole Photo Album API (`PhotoAlbum`,
  `PhotoAlbumItem`, 53 methods): albums, photos, ratings, flags, versions,
  per-photo effects and Fusion comps, stills. Verified 9/9 and 20/20 methods.
- **`node_graph`** — node labels, colours, enable state, tools, LUTs, cache;
  on a timeline clip or a photo.
- **`project_extras`** — render preset listing, audio render formats and
  codecs, transcription read/write.
- **`camera_comparison`** — the multi-camera comparison workflow: camera
  detection from clip names, 2x2 / split / explicit layouts, camera markers,
  per-camera bin sorting, and multi-track timeline construction.
- **`clip_position`** — placement and handle offsets (read-only; the writing
  calls are broken, see below).
- **`resolve-ext doctor`** — checks Python, finds the Resolve scripting API on
  Windows / macOS / Linux, tests the import and opens a live connection,
  reporting precisely which step failed and what to do about it.
- **`resolve-ext env`** — prints the exact MCP-client configuration for the
  machine it runs on, including which env vars are optional.
- Automatic platform path resolution: the server locates the Resolve scripting
  API itself, so a default installation needs no environment variables at all.
- GitHub Actions: offline checks on Windows, macOS and Linux (Python 3.10 and
  3.12), and a release workflow that builds, verifies the wheel in a clean
  virtualenv, and publishes.

### Measured on Resolve Studio 21.1.2.10, and reported as broken

Every one of these returns success — or `True` — while doing nothing, or is
destructive. The tools surface the failure with the measurement attached
instead of passing a false success to the caller.

- `TimelineItem.SetPosition` and `Timeline.MoveItems` return `False` for every
  input, including a no-op.
- ~~`Timeline.ExportFrame` fails for every `frameOffset`, while the same frames
  export fine through `TimelineItem.ExportFrame`.~~ **Wrong — corrected in
  1.0.1.** The function works; a relative offset is required.
- ~~`Timeline.DeleteGaps` returns `True` and moves nothing.~~ **Wrong —
  corrected in 1.0.1.** It works on a timeline whose metadata is consistent.
- `TimelineItem.SetLeftOffset` is destructive: on a clip at frame 400 with
  duration 120 it moved the clip to -85995 and inflated the duration to 86515
  frames. It extends the clip from source media; it does not nudge the edit
  point, and setting the offset back does not restore the original. Not exposed
  as a writable action.
- `MediaPool.AddToPhotoAlbum` adds nothing and returns an empty list. Use
  `MediaPool.CreatePhotoAlbumFromPhotos`, which was verified working.
- `Graph.ResetAllNodeColors` exists on a photo album graph but not on a
  timeline clip graph.
- `MediaPoolItem.GetNodeGraph` is not callable.
- `Project.UpdateRenderPreset` and `SetQuickExportEnabledForRenderPreset`
  return `False` for all 37 factory presets.
- `MediaPoolItem.SetTranscription` returns `False` for a clip with no
  existing transcript.
- ~~`Timeline.AddMarker` cannot place a marker on the clip at timeline
  position 0.~~ **Imprecise — corrected in 1.0.1.** `Timeline.AddMarker` works;
  it is `TimelineItem.AddMarker` on that clip that returns `True` and writes
  nothing.
- `AppendToTimeline` with `startFrame == endFrame` returns `None` — which
  affects single-frame media whose natural `endFrame` is 0.
- `SetProperty("PositionX"/"PositionY")` is silently ignored; the real keys are
  `Pan` / `Tilt`, in pixels (`+x` right, `+y` up).

### Notes

- Requires **DaVinci Resolve Studio** — external scripting is a Studio feature.
- Resolve must run with **Preferences → System → General → External scripting
  using → Local**.
- The `mcp` dependency is pinned `<2` because `mcp` 2.x breaks FastMCP.

[1.0.0]: https://github.com/CaptRauti/ResolveMCP-ext/releases/tag/v1.0.0
