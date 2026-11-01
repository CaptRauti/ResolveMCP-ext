# Contributing

This server exists to cover one gap: the Resolve scripting surfaces that the
mainstream MCP servers do not implement. Two rules keep it useful.

## 1. Verify against live Resolve, not against documentation

A type stub (`DaVinciResolveScript.pyi`) tells you an API **exists**. It does not
tell you it **works**. This project has already found four 21.1.2 calls that
exist, appear in the stubs, and are broken at runtime.

Before adding a surface:

1. Check the API is documented — the changelog and stubs ship with Resolve:
   - `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\CHANGELOG.md`
   - `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\DaVinciResolveScript.pyi`

2. Confirm it exists on the build:
   ```python
   hasattr(real_resolve_object, "TheMethod")
   ```

3. Confirm it **does something**:
   ```python
   before = read_something()
   result = call_it(...)
   after = read_something()
   assert after != before, "it returned success but nothing changed"
   ```

Step 3 is not optional. `Timeline.DeleteGaps` returns `True` and moves nothing;
a test that only checked the return value would have shipped that as working.

## 2. Report broken behaviour instead of hiding it

When a Resolve call lies — returns success without effect, or fails for every
valid input — the tool must say so, with the measurement attached. A caller that
trusts a false success corrupts a timeline.

The pattern used throughout `server.py`:

```python
res = tl.ExportFrame(off, opts) or {}
if not res.get("success"):
    return _err(
        f"Timeline.ExportFrame(frameOffset={off}) failed: {res.get('error')}. "
        "MEASURED on Resolve 21.1.2.10: this call returns 'frameOffset is out "
        "of range' for EVERY offset tried (0, 5, 100, 200, 216000, 216010) on "
        "a timeline whose items start at frame 0. Treat it as BROKEN and use "
        "action='item' instead."
    )
```

Include the exact inputs tried. "It doesn't work" is not actionable; "it fails
for these six offsets while the same frames export through another call" is.

## 3. Never expose a destructive call without an undo story

`TimelineItem.SetLeftOffset` extends a clip from source media rather than
nudging its edit point, and setting the offset back does not restore the
original position. It is therefore **not callable at all** — only the read side
is exposed. If you add a mutating surface, state what restores it, or leave it
out.

## Style

- One tool per functional area, with an `action` parameter and a `params` dict —
  matches how the mainstream servers are shaped, so a model that knows one knows
  this.
- Every tool's docstring lists its actions with their arguments and return
  shape. That docstring is the model's only manual.
- Errors are `{"error": "..."}` dicts, never exceptions.
- Return `{"success": True, ...}` on the happy path.
- Address objects by `item_id`/`clip_id` (the API's own unique id) **or** by name
  plus a track, never by name alone where duplicates are possible.

## Testing

```bash
# Resolve running, env vars exported, some test media present
python tests/test_e2e.py

# custom media
RESOLVE_EXT_TEST_MEDIA="D:/stills/*.png" python tests/test_e2e.py
```

The suite builds a scratch project, exercises everything, and deletes it again.
Keep it that way — never point it at a project someone cares about, and always
verify the project list is back to what it was.

## Adding to the "broken" list

If you find a new broken or destructive call, add it to the table in
`README.md` **and** make the corresponding tool action report it. A finding that
lives only in a commit message helps nobody.
