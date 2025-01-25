# Keyboard & Keypad Shortcuts Guide

## Basic Navigation
| Key on Device | Equivalent on Keyboard | Action |
|----------|-----------------|---------|
| `UP` <kbd>↑</kbd> | <kbd>↑</kbd>/<kbd>K</kbd> | Go up |
| `DOWN` <kbd>↓</kbd> | <kbd> ↓ </kbd>/<kbd>J</kbd> | Go down |
| `BACK` <kbd>⟲</kbd> | <kbd>←</kbd>/<kbd>H</kbd>/<kbd>Esc</kbd> | Go back one level |
| `HOME` <kbd>⌂</kbd> | <kbd>Backspace</kbd> | Return to home menu |
| `L1` | <kbd>1</kbd> | Select first item |
| `L2` | <kbd>2</kbd> | Select second item |
| `L3` | <kbd>3</kbd> | Select third item |

## Special Commands
| Shortcut | Equivalent on Keyboard | Action |
|----------|---------| ---------|
| `HOME` <kbd>⌂</kbd> + `L1` | <kbd>SHIFT</kbd> + <kbd>1</kbd> | Take screenshot |
| `HOME` <kbd>⌂</kbd> + `L2` | <kbd>SHIFT</kbd> + <kbd>2</kbd> | Take store snapshot |
| `HOME` <kbd>⌂</kbd> + `L3` | <kbd>SHIFT</kbd> + <kbd>3</kbd> | Start/Stop recording input keys |
| `BACK` <kbd>⟲</kbd> + `L3` | <kbd>CTRL</kbd> + <kbd>3</kbd> | Replay latest recorded keys sequence |
| `HOME` <kbd>⌂</kbd> + `BACK` <kbd>⟲</kbd> | <kbd>SHIFT</kbd> + <kbd>←</kbd>/<kbd>SHIFT</kbd> + <kbd>H</kbd>/<kbd>SHIFT</kbd> + <kbd>Esc</kbd> | Exit application |

Note: All shortcuts can be triggered either through the physical keypad or keyboard keys. The keyboard shortcuts are designed to mirror the keypad functionality for easier testing and development.

## Artifact Storage

### Screenshots
**Location**: `/opt/ubo/screenshots/`<br>
**Format**: PNG image files<br>
**Naming**: `ubo-screenshot-xxx.png`<br>
**Contents**:
- High-quality lossless images
- Captures the entire screen content
- Includes timestamp in filename for easy reference

### Snapshots of the store
**Location**: `/opt/ubo/snapshots/`<br>
**Format**: JSON files<br>
**Naming**: `ubo-screenshot-xxx.json`<br>
**Contents**:
- The content of each snapshot file is the dump of the redux store and it is used for debug and testing purposes.

### Recordings
**Location**: `/opt/ubo/recordings/`<br>
**Format**: JSON files<br>
**Naming**: `ubo-recording-xxx.json` and `active.json` for the last recording<br>
**Contents**:
- Sequence of keypad events
- Timing information
- State transitions
- Only the last recording can be replayed using BACK + L3 on device keypad

<b>Note</b>: All directories are automatically created if they don't exist. Files are never automatically deleted - manual cleanup may be required to manage storage space.
