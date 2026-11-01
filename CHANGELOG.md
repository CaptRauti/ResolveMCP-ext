# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- `Timeline.ExportFrame` fails for every `frameOffset`, while the same frames
  export fine through `TimelineItem.ExportFrame`.
- `Timeline.DeleteGaps` returns `True` and moves nothing.
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
- `Timeline.AddMarker` cannot place a marker on the clip at timeline
  position 0.
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
