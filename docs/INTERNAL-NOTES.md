# resolve-ext — DaVinci Resolve MCP-Erweiterung

Eigener MCP-Server, der die Lücken des Upstream-Servers
`samuelgursky/davinci-resolve-mcp` schließt. Liegt **außerhalb** des Checkouts,
damit `git pull` dort niemals diese Erweiterung überschreibt.

- **Server:** `C:\Users\stefa\resolve-ext\server.py`
- **Registriert als:** `mcp_servers.resolve-ext` in der Hermes-Config (flaches Format)
- **Tool-Prefix:** `mcp__resolve_ext__*` (nach Hermes-Neustart / `/reload-mcp`)
- **Python:** derselbe venv wie der Haupt-Server (`davinci-resolve-mcp\venv`)
- **Resolve-Laufzeit:** 21.1.2.10 Studio · Upstream-Server 4.18.2

---

## Warum es diesen Server gibt

Resolve **21.1.2** (22. Okt 2026) brachte eine ganze Reihe neuer Scripting-APIs.
Der Upstream-Server kennt davon fast nichts. Gemessen (Grep im Server-Code
gegen `hasattr` auf echte Resolve-Objekte) — **0 Treffer im Server, Symbol
existiert live auf dem Build:**

| Resolve 21.1.2 | Upstream-Server | resolve-ext |
|---|---|---|
| `Resolve.GetEffectsList` | ❌ | ✅ `effects.list_available` |
| `TimelineItem.AddEffect/GetEffects/DeleteEffects` | ❌ | ✅ `effects.apply/list_applied/remove` |
| `Effect.GetInfo/Get/SetIsEnabled/Get/SetIndex` | ❌ | ✅ `effects.set_enabled/reorder` |
| `TimelineItem.CopyAttributes` | ❌ | ✅ `clip_attrs.copy` |
| `Project.UpdateRenderPreset` | ❌ | offen |
| `Project.SetQuickExportEnabledForRenderPreset` | ❌ | offen |
| `Project.GetAudioRenderFormats/Codecs` | ❌ | offen |
| `MediaPoolItem.SetTranscription` | ❌ | offen |
| `TimelineItem/Timeline/MediaPoolItem.ExportFrame` | ❌ | offen |
| `TimelineItem.Get/SetLeftOffset/RightOffset/Position` | ❌ | offen |
| `Timeline.MoveItems` · `DeleteGaps` · `Get/SetIsEnabled` | ❌ | offen |
| `MediaPoolItem/Folder.GetParentFolder` | ❌ | offen |
| `Graph.SetNodeLabel/Get/SetNodeColor` | ❌ | offen |
| Photo Album APIs (komplett) | ❌ | offen |

---

## Tools

### `effects` — Clip-Effekte und Effekt-Properties

| Action | Zweck |
|---|---|
| `list_available(media_type?)` | Alle anwendbaren Effekte. `media_type`: `video` (default) / `photo` / `audio`. **Vor jedem `apply` aufrufen** — liefert die nötige `category`+`id`. |
| `list_applied(item_id?\|name?, category?)` | Effekte auf einem Clip, mit `index` und `enabled`. |
| `apply(item_id?\|name?, category, id)` | Effekt anwenden. |
| `remove(item_id?\|name?, category, indices?)` | Effekt(e) entfernen. |
| `set_enabled(item_id?\|name?, index, enabled)` | Effekt an/aus. |
| `reorder(item_id?\|name?, index, new_index)` | Position im Stack ändern. |

**Adressierung:** `item_id` (`GetUniqueId`) oder `name` + Track (`track_type`
default `video`, `track_index` default `1`).

### `clip_attrs` — Attribute zwischen Clips kopieren

| Action | Zweck |
|---|---|
| `options()` | Der vollständige Options-Wortschatz, gruppiert (36 Flags). |
| `copy(source_*, target_ids?\|target_names?, options)` | Attribute übertragen. |
| `read(item_id?\|name?)` | Lesbare Video-Attribute eines Clips. |

Die API hinter **Paste Attributes** — damit wird ein per-Kamera-Look
wiederholbar: einen Clip graden, dann dieselben Attribute auf alle Clips
dieser Kamera schieben.

**Options-Gruppen:** `clip`, `video`, `zoom_crop_flip`, `retime`,
`grade_fusion`, `audio`. Shorthands `copy_all_video` / `copy_all_audio`.

Typischer Kamera-Fall:
```json
{"colorCorrection": true, "allZoomAttributes": true,
 "allCropAttributes": true, "videoPlugins": true}
```

### `resolve_ext_status` — Health-Check

Meldet Verbindung, Produkt/Version, offenes Projekt, und welche Oberflächen
dieser Build unterstützt.

---

## Verifizierte Fakten (live gemessen, nicht aus Doku)

### Property-Keys sind beschreibbar
Alle geprüft mit `SetProperty` → `GetProperty` Rücklesung:

| Key | Einheit | Beispiel |
|---|---|---|
| `ZoomX` / `ZoomY` | Multiplikator | `1.5` |
| `Pan` / `Tilt` | Pixel (x / y) | `250.0` / `-120.0` |
| `RotationAngle` | Grad | `12.0` |
| `Opacity` | 0–100 | `70.0` |
| `CropLeft/Right/Top/Bottom` | 0–1 | `0.15` |

**Falle:** `GetProperty("Position")` liefert auf 21.1.2 einen **Boolean**, keine
Koordinaten. Die Position steckt in **`Pan`/`Tilt`**. Nie `Position` lesen.

### `CopyAttributes` funktioniert nachweislich
Scharfer Test (Quelle verändert → Ziel geprüft):

| Attribut | Quelle gesetzt | Ziel nach Copy |
|---|---|---|
| ZoomX/Y | 1.5 | **1.5** ✅ |
| Pan | 250.0 | **250.0** ✅ |
| Tilt | -120.0 | **-120.0** ✅ |
| RotationAngle | 12.0 | **12.0** ✅ |
| Opacity | 70.0 | 100.0 (nicht in Options — korrekt) ✅ |

### `Resolve.GetEffectsList` liefert live
- `video`: **36 Fusion + 98 OFX**
- `audio`: Fairlight-FX (Chain FX, Chorus, De-Esser, De-Hummer, …)
- Fusion-IDs haben die Form `Fusion/Effects/<Kategorie>/<Name>`
- Audio-IDs: `Audio FX/Fairlight FX/<Name>`

### Laufzeiten sind unkritisch
Alle Actions: **0–15 ms**. Kein `timeout` in der Server-Config nötig
(Standard reicht; `hermes mcp add` setzt keinen und das ist hier egal).

---

## Installation / Registrierung

```bash
cd /c/Users/stefa
hermes mcp add resolve-ext \
  --command "C:\Users\stefa\davinci-resolve-mcp\venv\Scripts\python.exe" \
  --env "RESOLVE_SCRIPT_API=C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting" \
        "RESOLVE_SCRIPT_LIB=C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll" \
        "PYTHONPATH=C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules" \
        "PYTHONHOME=C:\Python314" \
  --connect-timeout 60 \
  --args "C:\Users\stefa\resolve-ext\server.py"
```

Die Abfrage „Enable all 3 tools?" mit `Y` beantworten — **ohne Eingabe bricht
`hermes mcp add` mit „Cancelled" ab und speichert nichts** (mit `echo "Y" |`
davor automatisierbar).

**Die Hermes-Config ist für den Agenten schreibgeschützt** (`Refusing to write
to Hermes config file`). Immer über `hermes mcp add` gehen, nie per `patch`.

### Verifikation
```bash
hermes mcp list                     # resolve-ext muss "enabled" sein
hermes mcp test resolve-ext         # "✓ Connected (…ms) · ✓ Tools discovered: 3"
```

Zusätzlich prüfen, dass der Eintrag **flach** liegt (`mcp_servers.resolve-ext`,
nicht genestet unter `mcpServers:`) — Nesting deaktiviert die Discovery still.

### Direkt testen ohne MCP
```bash
cd /c/Users/stefa/resolve-ext
RESOLVE_SCRIPT_API="C:/ProgramData/Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting" \
RESOLVE_SCRIPT_LIB="C:/Program Files/Blackmagic Design/DaVinci Resolve/fusionscript.dll" \
PYTHONPATH="C:/ProgramData/Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting/Modules" \
"C:/Users/stefa/davinci-resolve-mcp/venv/Scripts/python.exe" -c "
import sys; sys.path.insert(0, r'C:\Users\stefa\resolve-ext')
import server as S, json
print(json.dumps(S.resolve_ext_status(), default=str, indent=2))
print(json.dumps(S.effects('list_available', {'media_type':'video'}), default=str)[:300])
"
```

---

## Wichtig beim Erweitern

- **Nach jeder Änderung:** Server-Prozess neu starten (Hermes `/reload-mcp`
  oder Neustart) — MCP-Prozesse halten alten Code, bekannter Fallstrick.
- **Neue Actions immer live gegen Resolve testen**, nicht gegen die Doku.
  `hasattr` auf einem echten Objekt ist der einzige verlässliche Nachweis,
  dass ein Symbol auf diesem Build existiert.
- **Testprojekte aufräumen:** `ZZ_*`-Projekte anlegen und danach löschen;
  Projektliste gegenprüfen (aktuell 24 Projekte, keine `ZZ_`-Reste).
- **Scharf testen:** Wenn ein Test „funktioniert" hat, aber die Werte vorher
  und nachher identisch waren, hat er nichts bewiesen. Quelle verändern und
  die Änderung im Ziel nachweisen.
