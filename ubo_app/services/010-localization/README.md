# Localization Service (`010-localization`)

## Overview

The localization service owns the device's language selection. It provides the
Settings → Localization → Language picker, persists the choice, and emits a change event so
downstream services (notably the assistant / speech-synthesis stack) can react — the selected
language governs which Piper voices are offered and used. Today it is language-only; future siblings
(units, time format, location) are meant to plug into the same `LOCALIZATION` settings category.

It loads in the `010-` tier — after the `000-` core services but before feature services — so the
language slice exists by the time services like `010-speech-synthesis` and `090-assistant` read it.
See [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md).

## Files

| Path            | Purpose                                                                     |
| --------------- | --------------------------------------------------------------------------- |
| `ubo_handle.py` | Registration; returns `init_service()`'s subscription list.                 |
| `setup.py`      | Runtime: Settings entry, language picker dynamic menu, per-language handlers.|
| `reducer.py`    | Pure reducer for the `localization` slice; emits the language-changed event.|

Store types: [`ubo_app/store/services/localization.py`](../../store/services/localization.py).

## State

Slice: `state.localization` — [`LocalizationState`](../../store/services/localization.py):

| Field      | Type           | Meaning                                                              |
| ---------- | -------------- | ------------------------------------------------------------------- |
| `language` | `LanguageCode` | Selected language family; persisted, default `EN`.                 |

`LanguageCode` is a `StrEnum` of eight families (`en`, `de`, `es`, `fr`, `it`, `pt`, `nl`, `zh`);
sub-locales/accents are handled at the voice level, not here. `language_label()` maps codes to
human-readable names. Persisted values are loaded through `_load_language`, which falls back to `EN`
on any unknown/invalid input.

## Actions & Events

Per the store contract, **events are emitted only from the reducer**.

| Action                          | Reducer result                                                              |
| ------------------------------- | -------------------------------------------------------------------------- |
| `LocalizationSetLanguageAction` | If the language changed: sets `language` and emits `LocalizationLanguageChangedEvent`. No-op (no event) if unchanged. |

## Runtime & Setup

`init_service()` (`setup.py:84`) is small: it registers the persistent store, the "open picker"
action, and the Settings entry, then returns `[]` (no subscriptions to tear down).

```python
register_persistent_store('localization:language', lambda state: state.localization.language)
register_action(OPEN_LANGUAGE_ACTION_ID, _open_language_picker, allow_reregister=True)
store.dispatch(RegisterSettingAppAction(
    category=SettingsCategory.LOCALIZATION,
    priority=0,
    label='Language',
    icon='󰗊',
    action_id=OPEN_LANGUAGE_ACTION_ID,
))
```

The reactive piece is `_build_language_menu` (`setup.py:53`) — `@store.autorun` on
`state.localization.language`. It rebuilds the language selection menu whenever the choice changes
(checkmarking the active language) and lazily (re)registers a `localization:set_language:<code>`
action handler per language.

## User Interface

- **Settings entry:** `RegisterSettingAppAction` under `SettingsCategory.LOCALIZATION` ("Language").
- **Open action:** `OPEN_LANGUAGE_ACTION_ID = 'localization:open_language_picker'` pushes the picker
  via `StackPushMenuAction(menu_key=LANGUAGE_MENU_ID)`.
- **Dynamic menu (dumb UI):** `LANGUAGE_MENU_ID = 'localization:language'`, a `build_selection_menu`
  over `LanguageCode` with per-option handlers `localization:set_language:<code>`.

## Cross-Service Interactions

- **`090-assistant`** reads `state.localization` and reacts to `LocalizationLanguageChangedEvent` to
  scope its Piper voice catalog / TTS to the chosen language. This consumer relationship is why
  localization loads (in `010-`) ahead of the assistant tier.

## Configuration

No env vars or secrets. Constants: `LANGUAGE_MENU_ID = 'localization:language'`,
`OPEN_LANGUAGE_ACTION_ID = 'localization:open_language_picker'`; persistent key
`localization:language` (default `EN`).

## Testing & Development Notes

Related tests:

| Test                                 | Tier        | What it covers                                                                 |
| ------------------------------------ | ----------- | ----------------------------------------------------------------------------- |
| `tests/store/test_localization.py`   | Unit        | Default = English; `_load_language` fallback on bad input and round-trip of known codes; `language_label`; reducer sets language + emits the event; reducer no-op when unchanged; persistence round-trips through the state file (incl. unknown/missing keys). Loads the service by file path with `importlib.reload` for class-identity discipline. |
| `tests/integration/test_services.py` | Integration | Asserts the `localization` service registers and the store snapshot matches.    |

**Maintenance when you change this service:**

- **State shape** (`LocalizationState`) or the language-menu output → regenerate store/window
  snapshots (never hand-edit them); this updates `test_services.py`.
- **Reducer branch / event** → cover it in `tests/store/test_localization.py` (prefer this pure-reducer
  unit test over an E2E flow).
- **Adding a `LanguageCode`** → extend `_LANGUAGE_LABELS`, ensure a curated Piper voice exists for it,
  and add round-trip/label cases to `test_localization.py`; the picker menu output also feeds
  snapshots, so regenerate them.
- **Persistence:** tests monkeypatch the persistent-store path to a tmp file — never let a test write
  the real `state.json`.

To exercise manually: Settings → Localization → Language, switch languages, and confirm the assistant
voice options update accordingly.
