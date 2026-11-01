# resolve-ext

An MCP server that adds the **DaVinci Resolve 21.1.2 scripting surfaces the
mainstream Resolve MCP servers do not cover** — clip effects, effect
properties, Paste-Attributes, frame export and media-pool folder lookups.

It is deliberately an **extension, not a replacement**: run it alongside
[`samuelgursky/davinci-resolve-mcp`](https://github.com/samuelgursky/davinci-resolve-mcp)
(or any other) and you get a larger surface with no overlap. Everything it
exposes is measured against a live Resolve, and calls that turn out to be broken
are reported as broken rather than wrapped in a success.

```
effects              apply/list/remove/toggle/reorder clip effects
clip_attrs           copy attributes between clips (Paste Attributes)
export_frame         stills from a clip or media-pool item
folder_ops           which bin does this clip/folder live in
photo_albums         albums, photos, ratings, flags, versions, stills
node_graph           node labels, colours, enable state, LUTs, cache
project_extras       render presets, audio render formats, transcription
camera_comparison    2x2 / split layouts, camera labels, markers
clip_position        read placement + handle offsets; flags broken APIs
resolve_ext_status   health check
```

## Why this exists

DaVinci Resolve **21.1.2** (22 Oct 2026) added a batch of scripting APIs. The
popular MCP servers do not implement them — verified two ways: searching their
source for each symbol, and probing live Resolve objects with `hasattr` (a type
stub documents the API; only the live object proves your build has it).

| Resolve 21.1.2 symbol | In mainstream MCP servers |
|---|---|
| `Resolve.GetEffectsList` | absent |
| `TimelineItem.AddEffect` / `GetEffects` / `DeleteEffects` | absent |
| `Effect.GetInfo` / `Get/SetIsEnabled` / `Get/SetIndex` | absent |
| `TimelineItem.CopyAttributes` | absent |
| `TimelineItem.ExportFrame` / `MediaPoolItem.ExportFrame` | absent |
| `MediaPoolItem.GetParentFolder` / `Folder.GetParentFolder` | absent |
| `TimelineItem.Get/SetLeftOffset` / `GetPosition` | absent |
| `Timeline.MoveItems` / `DeleteGaps` / `Get/SetIsEnabled` | absent |
| **Photo Album APIs** (`PhotoAlbum`, `PhotoAlbumItem`, 53 methods) | absent |
| `Graph.SetNodeLabel` / `Get/SetNodeColor` / `SetNodeEnabled` | absent |
| `Project.GetAudioRenderFormats` / `GetAudioRenderCodecs` | absent |
| `Project.UpdateRenderPreset` / `SetQuickExportEnabledForRenderPreset` | absent |
| `MediaPoolItem.SetTranscription` | absent |

`TimelineItem` alone exposes **113 methods** on 21.1.2; a large share of them
were unreachable through MCP before this server.

## Install

> **Installing this with an AI agent?** Point it at
> [AGENTS.md](AGENTS.md) — it is a step-by-step procedure written for agents,
> including the failure cases. This section is the human-facing version.

Requires **Python 3.10+** and **DaVinci Resolve Studio** (external scripting is
a Studio feature — the free build refuses it).

### From a release (recommended)

Download the wheel from the [releases page][releases] and install it:

```bash
pip install resolve_ext-1.0.0-py3-none-any.whl
```

The wheel is pure Python and platform-independent — the same file works on
Windows, macOS and Linux.

### From a git checkout

```bash
pip install git+https://github.com/CaptRauti/ResolveMCP-ext
```

Or from a local clone:

```bash
git clone https://github.com/CaptRauti/ResolveMCP-ext
cd ResolveMCP-ext
pip install .
```

`mcp` 2.x breaks FastMCP, so the dependency is pinned `<2`. That pin is in the
package metadata — you do not need to add it yourself.

### Verify the installation

```bash
resolve-ext doctor
```

```
resolve-ext 1.0.0

--- Python ---
  3.12.4 at /usr/bin/python3
  ok (3.10+)

--- DaVinci Resolve scripting API ---
platform      linux
api_path      /opt/resolve/Developer/Scripting  (found)
lib_path      /opt/resolve/libs/fusionscript.so  (found)

--- Import test ---
  ok: DaVinciResolveScript imports

--- Live connection ---
  ok: connected to Resolve; project = My Project

--- Result ---
  All checks passed.
```

`doctor` exits `0` when everything works and `1` otherwise, so it is usable in
a setup script. When something is wrong it names the exact path that is missing
and what to enable.

### Register with your MCP client

The server finds Resolve's scripting API by itself, so on a default
installation there is **nothing to configure**:

```json
{
  "mcpServers": {
    "resolve-ext": { "command": "resolve-ext" }
  }
}
```

For a non-standard Resolve location, or to see the explicit form, run:

```bash
resolve-ext env
```

which prints the configuration for the machine it runs on — including the exact
`RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB` and `PYTHONPATH` values — as generic
JSON and as a `hermes mcp add` command.

When merging into an existing client config, the server entry sits **flat**
under the client's own `mcpServers` key. Do not wrap it in a second
`mcpServers` level — that silently disables tool discovery.

### Resolve settings

Resolve must be running with **Preferences → System → General → External
scripting using → Local**.

[releases]: https://github.com/CaptRauti/ResolveMCP-ext/releases

## Tools

### `effects`

```
list_available(media_type?)          video (default) | photo | audio
list_applied(item_id?|name?, category?)
apply(item_id?|name?, category, id)
remove(item_id?|name?, category, indices?)
set_enabled(item_id?|name?, index, enabled, category?)
reorder(item_id?|name?, index, new_index, category?)
```

Address a timeline item with `item_id` (`GetUniqueId`) or with `name` plus the
track it sits on (`track_type` default `video`, `track_index` default `1`).

Always call `list_available` first — `apply` needs the `category` and `id` it
returns. On a stock 21.1.2 Studio that is **36 fusion + 98 ofx** effects for
`video`, plus the Fairlight set for `audio`. Fusion ids look like
`Fusion/Effects/<category>/<name>`.

### `clip_attrs`

```
options()                                    the full option vocabulary
copy(source_id?|source_name?, target_ids?|target_names?, options, ...)
read(item_id?|name?)
```

The API behind the Edit page's **Paste Attributes** — the lever that makes a
per-camera look repeatable: grade one clip, push the same attributes onto every
other clip from that camera.

36 options in 6 groups (`clip`, `video`, `zoom_crop_flip`, `retime`,
`grade_fusion`, `audio`). Shorthands: `copy_all_video`, `copy_all_audio`.

```json
{"colorCorrection": true, "allZoomAttributes": true,
 "allCropAttributes": true, "videoPlugins": true}
```

### `export_frame`

```
item(item_id?|name?, frame_offset, output_type?, file_path?, format?, max_dimension?)
media(clip_id, frame_offset, output_type?, file_path?, format?, max_dimension?)
timeline(frame_offset, ...)     # broken on 21.1.2 — see below
```

`item` and `media` are verified working. The offset is 0-based and must be
below the item's duration. `output_type`: `file` (needs `file_path`) or
`encodedString` (default); for the latter the base64 is decoded and written to
`out/` next to the server, with only a short prefix returned inline.

### `folder_ops`

```
parent_of_clip(clip_id)              which bin holds this clip
parent_of_folder(path?|folder_id?)   a folder's parent (root has none)
path(clip_id?|folder_id?)            "Master/Sub/Bin"
find_clip(clip_id)                   locate a clip anywhere in the tree
```

### `photo_albums`

```
list() / current() / set_current(album_id?|name?)
create(name) / create_from_photos(name, clip_ids) / delete(album_ids?) / rename(...)
quick_export_presets() / render_settings(settings?)
photos(album_id?|name?) / add_photos(clip_ids) / remove_photos(photo_ids) / current_item()
stills(album_id?|name?, all_photos?)
photo(photo_id) / rate(photo_id, stars) / flag(photo_id, color?|clear?)
clip_color(photo_id, color?|clear?) / versions(photo_id)
add_version / load_version / delete_version
copy_grade / effects_list / effect_apply / effect_remove / fusion_comps / fusion_add
```

Verified working on 21.1.2.10: **9/9 `PhotoAlbum` methods, 20/20
`PhotoAlbumItem` methods**, `CreatePhotoAlbumFromPhotos`, persistent ratings /
flags / versions, `AddFusionComp` on a photo.

`add_photos` is **broken upstream** (`AddToPhotoAlbum` adds nothing) — the
action verifies by reading the album back and tells you so. Use
**`create_from_photos`**, which is the verified path.

> Note the split: the album *listing* methods live on `Project`, the
> *creating/adding* ones on `MediaPool`, and Resolve answers none of them. The
> tool resolves the right object per call, because a Resolve proxy makes
> `hasattr` report every method on every object.

### `node_graph`

```
info(item_id?|name?|photo_id?)        node list with labels and colours
label(node_index, label)              "" clears the label
color(node_index, color)              "" clears the colour
enable(node_index, enabled)
tools(node_index)                     which Fusion/OFX tools sit in the node
lut(node_index, lut_path?)            read, or set
cache(node_index, mode?)              read, or set
reset_colors()                        photo graphs only
reset_grades(confirm=true)            destructive — clears the whole grade
```

Valid node colours: Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy,
Blue, Purple, Violet, Pink, Tan, Beige, Brown, Chocolate.

Target a timeline clip by `item_id`/`name`, or a photo by `photo_id`. Labels
and colours verified persistent across calls.

### `project_extras`

```
capabilities()                             what this build answers at all
render_presets()                           GetRenderPresetList
update_render_preset(preset_name)          GUI-dependent, see the broken table
quick_export_enable(preset_name, enabled)  GUI-dependent
audio_formats()                            {display name -> extension}
audio_codecs(format_extension)             {description -> codec name}
transcription(clip_id, use_nested?)        a clip's transcript
set_transcription(clip_id, transcription)  verified by reading back
```

`audio_formats` / `audio_codecs` VERIFIED: 7 real formats
(`FLAC, MP3, MP4, MXF OP-Atom, MXF OP1A (IMF), QuickTime, Wave`) and their
codecs. `render_presets` VERIFIED: 37 real presets.

### `camera_comparison`

```
detect()                 which camera each clip is (from its name)
grid_2x2()               four cameras in quadrants, scale 0.5
split_h() / split_v()    two-up, side by side or stacked
layout(assignments)      explicit {clip_id: {x, y, scale}} — fractions of raster
fullframe(clip_ids)      back to 1.0 zoom, centred
markers()                timeline markers naming each camera
sort_to_bins()           file clips into per-camera bins by name
build_timeline()         one video track per camera, scenes synced
read()                   current transform of every clip
```

Camera detection, longest prefix first:

| prefix | camera | marker |
|---|---|---|
| `ace*` | Insta360 AcePro | Orange |
| `go*` | Insta360 Go Ultra | Green |
| `luna*` | Insta360 Luna Ultra | Cyan |
| `x*` | Insta360 X5 | Blue |
| `vid_*` | Handy (Android file) | Gray |

**Why this tool exists:** the loose scripts this replaces positioned clips
with `SetProperty("PositionX", …)` / `"PositionY"`. MEASURED on 21.1.2.10 those
keys return **`False` and are silently ignored** — `GetProperty` gives back
`False` too. Zoom worked, the positioning never did. The real keys are **`Pan`**
(x, +right) and **`Tilt`** (y, **+up**), in pixels. Every write here is read
back, and a transform that does not stick is reported as a failure.

Verified: on a 3840x2160 timeline `grid_2x2` puts AcePro at `Pan -960, Tilt
540` (top-left) and Go Ultra at `Pan 960, Tilt 540` (top-right), read back.

### `clip_position`

```
get(item_id?|name?)      position + left/right handle offsets   (safe, read-only)
enabled()                timeline enabled state
```

`set` / `move` / `set_offset` / `delete_gaps` exist in the code but are
**disabled and transparent about why** — they wrap Resolve calls that are broken
or destructive on 21.1.2. See the next section.

## Measured behaviour on Resolve 21.1.2.10

Everything below was measured against a live Studio build, not read from docs.
`tests/` reproduces all of it — 132 assertions across four suites, 0 failures.

**Working**

| Call | Result |
|---|---|
| `Resolve.GetEffectsList` | 36 fusion + 98 ofx (video), Fairlight (audio) |
| `TimelineItem.AddEffect` / `GetEffects` / `DeleteEffects` | verified end to end |
| `Effect.GetInfo` / `GetIsEnabled` / `SetIsEnabled` / `GetIndex` | verified |
| `TimelineItem.CopyAttributes` | verified with changed source values |
| `TimelineItem.ExportFrame` | offsets `0..duration-1` succeed, beyond is refused |
| `MediaPoolItem.ExportFrame` | verified, file written |
| `MediaPoolItem` / `Folder.GetParentFolder` | verified |
| `Timeline.GetIsEnabled` / `SetIsEnabled` | verified |

**Broken or destructive — do not use**

| Call | Measured behaviour |
|---|---|
| `TimelineItem.SetPosition` | Returns `False` for **every** input — real video clips and stills, int and float `startFrame`, a no-op equal to the current frame, both `moveLinkedItems` values. `Timeline.MoveItems` behaves identically, while `SetCurrentTimecode` succeeds in the same session. |
| `Timeline.ExportFrame` | `frameOffset is out of range for the timeline` for every offset tried (0, 5, 100, 200, 216000, 216010) on a timeline whose items start at frame 0 — while the same frames export fine through `TimelineItem.ExportFrame`. |
| `Timeline.DeleteGaps` | Returns `True` and moves nothing — a silent no-op. |
| `TimelineItem.SetLeftOffset` | **Destructive.** On a clip at frame 400 with duration 120, `SetLeftOffset(5)` moved it to **-85995** and inflated the duration to **86515** frames: it *extends the clip from source media*, it does not nudge the edit point. Setting the offset back to `0` did **not** restore the original position (the clip stayed at -86000). There is no API-level undo. |
| `MediaPool.AddToPhotoAlbum` | Adds nothing and returns an empty list. Tested four ways: immediately after `CreateEmptyPhotoAlbum`, with a 2 s pause, after an explicit `SetCurrentPhotoAlbum` that `GetCurrentPhotoAlbum` confirmed, and with a fresh album each time — zero photos every run. `MediaPool.CreatePhotoAlbumFromPhotos` VERIFIED working (photos land and read back), so use that. |
| `Graph.ResetAllNodeColors` | Exists on a photo album item's graph but **not** on a timeline clip's graph (`NoneType is not callable`). Clearing a colour with `SetNodeColor(i, "")` works on both. |
| `MediaPoolItem.GetNodeGraph` | Not callable on 21.1.2.10 (while `TimelineItem.GetNodeGraph` and `PhotoAlbumItem.GetNodeGraph` both work). Put the clip on a timeline and address it by `item_id`. |
| `Project.UpdateRenderPreset` | Returns `False` for all 37 factory presets that `GetRenderPresetList` reports (`'H.264 Master'` included). `Project.SaveRenderPreset` does not exist in the API, so a user preset cannot be created from scripting to test against. GUI-dependent at best. |
| `Project.SetQuickExportEnabledForRenderPreset` | Same shape: `False` for a factory preset. |
| `MediaPoolItem.SetTranscription` | Returns `False` for a PNG still **and** for a real video clip with no transcript, with both `'01:00:00:00'` and `'00:00:00:00'` start timecodes. It *replaces* a transcript, so it appears unable to create one where none exists. |
| `MediaPoolItem.SetClipColor` (photo items) | Returned `False` for `'Sky'` on a photo album item while the colour list is documented; `ClearClipColor` works. The action reports the rejection rather than assuming success. |
| `Folder.AddSubFolder` / `Folder.MoveClips` | Do not exist. Both live on **MediaPool** (`mp.AddSubFolder(parent, name)`, `mp.MoveClips(clips, folder)`) — verified that `MoveClips` really relocates the clip and returns `True`, not a false success. Same object-split as the photo-album API. |
| `TimelineItem.SetProperty("PositionX"/"PositionY")` | **Silently ignored** — both the setter and the getter return `False`. Use `Pan` / `Tilt` (pixels, +x right, +y up). This is what broke the project's own grid scripts: zoom applied, positions never did. |
| `Timeline.AddMarker` on the clip at position 0 | Cannot be placed — neither the relative frame (`0`) nor the absolute one (`StartFrame + 0`) is accepted, while every other clip answers. The tool tries both and lists the clip under `failed`. |
| `AppendToTimeline` with `startFrame` == `endFrame` | Returns `None` and places nothing. With single-frame media (`GetClipProperty("Frames") == "1"`) the natural `endFrame` is `0`, so a "correct" 0..0 range silently fails. Omitting `endFrame` lets Resolve use the whole clip and works. |

**Gotchas**

- `TimelineItem.GetProperty("Position")` returns a **bool** on 21.1.2, not
  coordinates. The position lives in **`Pan` / `Tilt`** (x/y in pixels).
  `RotationAngle` is degrees, `Opacity` 0–100, crop values 0–1, `ZoomX/Y` a
  multiplier. All are writable — verify with a read-back.
- Setting a timeline's `SetIsEnabled(False)` makes `GetCurrentTimeline()` return
  `None`, so every later call reports "No current timeline" until it is switched
  back on in the GUI.
- `MediaPoolItem.GetParentFolder` is only useful with a recursive walk of the
  media pool: `ImportMedia` drops clips into the currently *selected* bin, so a
  root-only lookup reports "not found" while the clip exists one level down.

## Testing

Two layers, because DaVinci Resolve cannot run in CI.

### Offline — no Resolve needed, this is what CI runs

```bash
python tests/test_offline.py
```

Checks that `server.py` imports **without** Resolve present (so `pip install`
followed by `resolve-ext --help` cannot fail), that all ten tools register,
that the CLI returns the right exit codes, and that the platform path
resolution produces the correct paths for the OS it finds itself on. Runs on
Windows, macOS and Linux — see `.github/workflows/test.yml`.

### Live — needs a running Resolve Studio

```bash
python tests/test_e2e.py        # core tools
python tests/test_phase1.py     # photo albums + node graph
python tests/test_extras.py     # render presets, audio formats, transcription
python tests/test_camera.py     # camera layouts, labels, markers, sorting

# point at your own media if ~/Pictures has fewer than 3 PNGs
RESOLVE_EXT_TEST_MEDIA="D:/stills/*.png" python tests/test_camera.py
```

**162 assertions, 0 failures** against Resolve Studio 21.1.2.10
(30 offline + 132 live).

Each suite creates its own scratch project, exercises the tools and deletes it
again — they never touch your other projects. Two habits are deliberate:

- Assertions check that values **changed and read back**, not merely that no
  error was returned. A write test that passes because nothing moved proves
  nothing; that is exactly how `DeleteGaps` and `AddToPhotoAlbum` were caught
  reporting success while doing nothing.
- Known-broken calls are asserted to *fail honestly*. If a future Resolve build
  fixes `AddToPhotoAlbum`, its test will start failing — which is the signal to
  re-measure and update this README, not a broken test.

## Design notes

- **Extension, not fork.** Nothing here duplicates a mainstream server's
  surface, so both can run side by side without the model having to choose.
- **Broken APIs are reported, not hidden.** Where Resolve's own call lies
  (`DeleteGaps` returning `True`), the tool says so with the measurement
  attached, rather than emitting a success the caller cannot trust.
- **Destructive APIs are not exposed.** `SetLeftOffset` cannot be undone through
  the API, so it stays out of the surface and `get` remains read-only.

## Requirements

- DaVinci Resolve **Studio 21.1.2+** (earlier builds lack these symbols)
- Windows / macOS / Linux wherever the Resolve scripting API is available
- Python 3.10+ and `mcp[cli]>=1.30,<2`

## License

MIT — see [LICENSE](LICENSE).
