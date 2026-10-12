# Windows-style Window Shortcuts

A small MIT-licensed KWin script for KDE Plasma 6. Familiar keyboard window
management without replacing your window manager or adding a background daemon.

## Install and uninstall

Run these as your regular desktop user, from a terminal inside your KDE session:

```sh
git clone https://github.com/niposch/kwin-windows-shortcuts.git
cd kwin-windows-shortcuts
./install.sh
```

Active immediately and at future Plasma logins. No sudo, logout or KWin restart.
Running `./install.sh` again updates the script while retaining the original backup.

```sh
./uninstall.sh
```

Uninstall unloads the script, removes its package/shortcuts and restores the
shortcuts displaced during installation. Other settings and shortcuts are left
alone. If you subsequently edit a displaced shortcut, uninstall preserves that edit.
The local backup lives at `$XDG_STATE_HOME/kwin-windows-shortcuts/install.json`
(normally `~/.local/state/kwin-windows-shortcuts/install.json`). Keep it until uninstall.

Requires KWin/Plasma **6.7 or newer**, Python 3 with PyGObject (`gi`),
`kpackagetool6`, `kwriteconfig6` and `kreadconfig6`. Developed on Fedora 44,
KWin 6.7.5, Wayland. Older Plasma releases have different tiling APIs.

## Shortcuts

| Shortcut | Behavior |
|---|---|
| Win+Left / Right | Snap to a side; native KWin corner/adjacent-monitor cycling |
| Win+Up | Maximize; repeated Up stays maximized |
| Win+Down | Restore maximized window, then minimize on the next press |
| Side-snapped + Win+Up / Down | Upper/lower corner on that side |
| Upper corner + Win+Down | Return to the side half |
| Lower corner + Win+Up | Return to the side half |
| Upper corner + Win+Up | Maximize |
| Lower corner + Win+Down | Restore original size; next Down minimizes |
| Win+Shift+Left / Right | Native directional monitor move, retaining snapped/maximized state |

“Win” is KDE's Meta key. Existing Meta+PgUp/PgDown and Meta+Backspace remain
available. Meta+Alt+arrows still focus neighboring windows.

The goal is comfortable Windows-like behavior, not an exact Windows clone.
No Snap Assist chooser, snap groups or Win+Z overlay. Repeated horizontal keys
use KWin's existing behavior; a missing adjacent monitor is handled by KWin.
Application size constraints/window rules may prevent particular sizes. Fullscreen
windows, special windows and interactive move/resize are ignored. On RDP, shortcuts
must be forwarded to the Linux desktop by the client.

## Quick test

1. In a normal window: Win+Up twice, then Win+Down. It should stay maximized
   through both Up presses and restore on Down. Another Down minimizes.
2. Win+Left, Up: upper-left quarter. Down: left half. Down: lower-left quarter.
   Down again: original size. Repeat with Right.
3. Win+Shift+Left/Right: move to the neighboring screen while retaining the
   snapped or maximized layout.

## Development

The script uses native KWin tiling, maximization, restoration and monitor moves;
it doesn't cache pixel rectangles or monitor IDs. Installation uses KGlobalAccel's
live D-Bus API and saves only conflicting shortcut assignments. State files stay
outside the repository.

```sh
node --test tests/behavior.test.cjs
python3 tools/manage.py status
```

Optional live tests require PySide6 and move only a disposable test window:

```sh
QT_QPA_PLATFORM=wayland /usr/bin/python3 tests/live-smoke.py
QT_QPA_PLATFORM=xcb /usr/bin/python3 tests/live-smoke.py
```

Node is only required for development tests. The runtime script is original code;
it does not incorporate third-party KWin scripts. See [LICENSE](LICENSE).
