# Keyboard & Keypad Shortcuts Guide

## Basic Navigation
| Shortcut | Alternative Keys | Action |
|----------|-----------------|---------|
| UP | K | Move selection up |
| DOWN | J | Move selection down |
| BACK | ESC, H, ← | Go back one level |
| HOME | Backspace | Return to home menu |
| L1 | 1 | Select first item |
| L2 | 2 | Select second item |
| L3 | 3 | Select third item |

## Special Commands
| Shortcut | Action |
|----------|---------|
| HOME + L1 | Take screenshot |
| HOME + L2 | Take snapshot |
| HOME + L3 | Start/Stop recording sequence |
| BACK + L3 | Replay recorded sequence |
| HOME + BACK | Exit application |
| CTRL + M | Toggle input mute |

## Advanced Navigation
| Shortcut | Action |
|----------|---------|
| CTRL + UP/K | Move up with BACK modifier |
| CTRL + DOWN/J | Move down with BACK modifier |
| SHIFT + UP/K | Move up with HOME modifier |
| SHIFT + DOWN/J | Move down with HOME modifier |

## Demo Features
| Shortcut | Action |
|----------|---------|
| HOME + UP | Show progress notification demo |
| HOME + DOWN | Show spinner notification demo |

Note 1: Demo notifications can be managed through the Notification Manager (Prss L2 on keypad), where individual notifications can be deleted.

Note 2: All shortcuts can be triggered either through the physical keypad or keyboard keys. The keyboard shortcuts are designed to mirror the keypad functionality for easier testing and development.

## Artifact Storage

### Screenshots
**Location**: `/opt/ubo/screenshots/`
**Format**: PNG image files
**Naming**: `ubo-screenshot-xxx.png`
- High-quality lossless images
- Captures the entire screen content
- Includes timestamp in filename for easy reference

### Snapshots
**Location**: `/opt/ubo/recordings/`
**Format**: JSON files
**Naming**: `ubo-recording-xxx.json` and `active.json` for the last recording


### Recordings
**Location**: `/opt/ubo/recordings/`
**Format**: Binary sequence files (.seq)
**Naming**: `recording_YYYY-MM-DD_HH-MM-SS.seq`
**Contents**:
- Sequence of keypad events
- Timing information
- State transitions
- Only the last recording can be replayed using BACK + L3

Note: All directories are automatically created if they don't exist. Files are never automatically deleted - manual cleanup may be required to manage storage space.