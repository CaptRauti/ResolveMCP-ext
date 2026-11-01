# resolve-ext

An MCP server that adds the **DaVinci Resolve 21.1.2 scripting surfaces the
mainstream Resolve MCP servers do not cover** — clip effects, effect
properties, Paste-Attributes, frame export and media-pool folder lookups.

It is deliberately an **extension, not a replacement**: run it alongside
[`samuelgursky/davinci-resolve-mcp`](https://github.com/samuelgursky/davinci-resolve-mcp)
(or any other) and you get a larger surface with no overlap.

```
effects              apply/list/remove/toggle/reorder clip effects
clip_attrs           copy attributes between clips (Paste Attributes)
export_frame         stills from a clip or media-pool item
folder_ops           which bin does this clip/folder live in
clip_position        read placement + handle offsets; flags two broken APIs
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

`TimelineItem` alone exposes **113 methods** on 21.1.2; a large share of them
were unreachable through MCP before this server.

## Install

```bash
git clone <this repo> resolve-ext
cd resolve-ext
pip install "mcp[cli]>=1.30,<2"
```

`mcp` 2.x breaks FastMCP, so keep the `<2` pin.

### Register with your MCP client

The server speaks **stdio** and needs the environment the official Resolve
scripting API expects, so that `import DaVinciResolveScript` resolves.

```bash
# Hermes
hermes mcp add resolve-ext \
  --command "<python.exe>" \
  --env "RESOLVE_SCRIPT_API=C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting" \
        "RESOLVE_SCRIPT_LIB=C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll" \
        "PYTHONPATH=C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules" \
  --connect-timeout 60 \
  --args "<abs path to>/server.py"
```

Generic JSON. When merging into an existing config the server entry sits
**flat** under the client's own `mcpServers` key — do not wrap it in a second
`mcpServers` level, that silently disables tool discovery:

```json
{
  "mcpServers": {
    "resolve-ext": {
      "command": "python.exe",
      "args": ["C:\\path\\to\\resolve-ext\\server.py"],
      "env": {
        "RESOLVE_SCRIPT_API": "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting",
        "RESOLVE_SCRIPT_LIB": "C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\fusionscript.dll",
        "PYTHONPATH": "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules"
      }
    }
  }
}
```

Resolve must run with **Preferences → General → External scripting → Local**,
and external scripting is **Studio-only** — the free build refuses it.

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
`tests/test_e2e.py` reproduces all of it — 33 assertions, 0 failures.

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

```bash
# requires Resolve running plus the env vars exported
python tests/test_e2e.py

# point at your own media if ~/Pictures has fewer than 3 PNGs
RESOLVE_EXT_TEST_MEDIA="D:/stills/*.png" python tests/test_e2e.py
```

The suite creates a scratch project (`ZZ_ExtFull`), exercises every tool and
deletes it again. It never touches your other projects. Assertions check that
values **changed**, not merely that no error was returned — a write test that
passes because nothing moved proves nothing.

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
