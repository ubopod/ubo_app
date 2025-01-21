# Keyboard & Keypad Shortcuts Guide

## Basic Navigation
| Key on Device | Equivalent on Keyboard | Action |
|----------|-----------------|---------|
| UP | ARROW_UP, or K | Move selection up |
| DOWN | ARROW_DOWN, or J | Move selection down |
| BACK | ESC, H, ← | Go back one level |
| HOME | Backspace | Return to home menu |
| L1 | 1 | Select first item |
| L2 | 2 | Select second item |
| L3 | 3 | Select third item |

## Special Commands
| Shortcut | Equivalent on Keyboard | Action |
|----------|---------| ---------|
| HOME + L1 | Backspace + 1 | Take screenshot |
| HOME + L2 | Backspace + 2 | Take store snapshot |
| HOME + L3 | Backspace + 3 | Start/Stop recording input keys |
| BACK + L3 | ESC, H, or ← + 3 | Replay latest recorded keys sequence |
| HOME + BACK | Backspace + ESC, H, or ← | Exit application |

Note: All shortcuts can be triggered either through the physical keypad or keyboard keys. The keyboard shortcuts are designed to mirror the keypad functionality for easier testing and development.

## Artifact Storage

### Screenshots
**Location**: `/opt/ubo/screenshots/`
**Format**: PNG image files
**Naming**: `ubo-screenshot-xxx.png`
- High-quality lossless images
- Captures the entire screen content
- Includes timestamp in filename for easy reference

### Snapshots of the store
**Location**: `/opt/ubo/snapshots/`
**Format**: JSON files
**Naming**: `ubo-screenshot-xxx.json`
**Contents**:
- The content of each snapshot file is the dump of the redux store and it is used for debug and testing purposes.

### Recordings
**Location**: `/opt/ubo/recordings/`
**Format**: JSON files
**Naming**: `ubo-recording-xxx.json` and `active.json` for the last recording
**Contents**:
- Sequence of keypad events
- Timing information
- State transitions
- Only the last recording can be replayed using BACK + L3 on device keypad

Note: All directories are automatically created if they don't exist. Files are never automatically deleted - manual cleanup may be required to manage storage space.