#!/usr/bin/python3
"""Install/uninstall without restarting KWin or replacing entire config files."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

PLUGIN = "kwin-windows-shortcuts"
ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / PLUGIN
STATE = STATE_DIR / "install.json"
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
PACKAGE = DATA / "kwin/scripts" / PLUGIN
BINDINGS = {
    "Left": 0x11000012, "Right": 0x11000014,
    "Up": 0x11000013, "Down": 0x11000015,
    "MonitorLeft": 0x13000012, "MonitorRight": 0x13000014,
}


def command(*args):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(" ".join(args) + ": " + (result.stderr or result.stdout).strip())
    return result.stdout.strip()


class Desktop:
    def __init__(self):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def call(self, dest, path, interface, method, signature=None, args=()):
        params = self.GLib.Variant(signature, args) if signature else None
        result = self.bus.call_sync(dest, path, interface, method, params, None,
                                   self.Gio.DBusCallFlags.NONE, 10000, None)
        return result.unpack()

    def accel(self, method, signature, args):
        return self.call("org.kde.kglobalaccel", "/kglobalaccel",
                         "org.kde.KGlobalAccel", method, signature, args)

    def scripting(self, method, signature, args):
        return self.call("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting",
                         method, signature, args)

    def keys(self, action):
        return [list(item[0]) for item in self.accel("shortcutKeys", "(as)", (action,))[0]]

    def set_keys(self, action, keys):
        self.accel("setForeignShortcutKeys", "(asa(ai))",
                   (action, [(sequence,) for sequence in keys]))
        # KGlobalAccel normalizes an empty binding as a zero sequence.
        if normalize(self.keys(action)) != normalize(keys):
            raise RuntimeError("Could not assign shortcut for " + action[1])

    def loaded(self):
        return self.scripting("isScriptLoaded", "(s)", (PLUGIN,))[0]

    def unload(self):
        if self.loaded():
            self.scripting("unloadScript", "(s)", (PLUGIN,))
            deadline = time.monotonic() + 3
            while self.loaded():
                if time.monotonic() > deadline:
                    raise RuntimeError("KWin did not unload the script")
                time.sleep(0.05)

    def load(self):
        script_id = self.scripting("loadScript", "(ss)",
                                   (str(PACKAGE / "contents/code/main.js"), PLUGIN))[0]
        if script_id < 0:
            raise RuntimeError("KWin could not load the script")
        self.call("org.kde.KWin", f"/Scripting/Script{script_id}",
                  "org.kde.kwin.Script", "run")
        deadline = time.monotonic() + 5
        while True:
            names = self.call("org.kde.kglobalaccel", "/component/kwin",
                              "org.kde.kglobalaccel.Component", "shortcutNames")[0]
            if all("WindowsShortcuts" + suffix in names for suffix in BINDINGS):
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Script did not register its shortcuts; inspect KWin logs")
            time.sleep(0.1)
        for suffix, key in BINDINGS.items():
            self.set_keys(own_action(suffix), [[key, 0, 0, 0]])


def normalize(keys):
    return [list(sequence) for sequence in keys if any(sequence)]


def own_action(suffix):
    return ["kwin", "WindowsShortcuts" + suffix, "KWin", "Windows-style " + suffix]


def snapshot(desktop):
    conflicts = {}
    for key in BINDINGS.values():
        for info in desktop.accel("getGlobalShortcutsByKey", "(i)", (key,))[0]:
            action = [info[2], info[0], info[3], info[1]]
            if info[4] != "default":
                raise RuntimeError("Non-default shortcut context conflicts: " + info[0])
            if action[1].startswith("WindowsShortcuts"):
                raise RuntimeError("Existing WindowsShortcuts actions have no saved installation state")
            conflicts[tuple(action)] = desktop.keys(action)
    entries = []
    for action, keys in conflicts.items():
        after = [sequence for sequence in keys
                 if not (sequence[0] in BINDINGS.values() and not any(sequence[1:]))]
        entries.append({"action": list(action), "before": keys, "after": after})
    previous = command("kreadconfig6", "--file", "kwinrc", "--group", "Plugins",
                       "--key", PLUGIN + "Enabled", "--default", "__absent__")
    return {"format": 1, "plugin_before": previous, "conflicts": entries}


def save(state):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(STATE)


def enable(value):
    args = ["kwriteconfig6", "--file", "kwinrc", "--group", "Plugins",
            "--key", PLUGIN + "Enabled"]
    command(*(args + (["--delete"] if value == "__absent__" else [value])))


def uninstall(desktop):
    if not STATE.exists():
        print("Not installed by this installer; no changes made.")
        return
    state = json.loads(STATE.read_text())
    # Disable first, then unload only this script. No global reconfigure/restart.
    enable("false")
    desktop.unload()
    for suffix in BINDINGS:
        desktop.accel("unregister", "(ss)", ("kwin", "WindowsShortcuts" + suffix))
    for entry in state["conflicts"]:
        current = desktop.keys(entry["action"])
        if normalize(current) == normalize(entry["after"]) or normalize(current) == normalize(entry["before"]):
            desktop.set_keys(entry["action"], entry["before"])
        else:
            print("Preserved a shortcut edited since installation:", entry["action"][1])
    if PACKAGE.exists():
        command("kpackagetool6", "--type", "KWin/Script", "--remove", PLUGIN)
    enable(state["plugin_before"])
    STATE.unlink()
    print("Uninstalled. Original conflicting shortcuts restored; later edits preserved.")


def install(desktop):
    if not STATE.exists():
        if PACKAGE.exists():
            raise RuntimeError("Package already exists without a backup; remove it in KWin Scripts first")
        save(snapshot(desktop))
    state = json.loads(STATE.read_text())
    try:
        desktop.unload()
        for entry in state["conflicts"]:
            desktop.set_keys(entry["action"], entry["after"])
        command("kpackagetool6", "--type", "KWin/Script",
                "--upgrade" if PACKAGE.exists() else "--install", str(ROOT / "package"))
        enable("true")
        desktop.load()
    except Exception:
        print("Installation failed; restoring saved settings.", file=sys.stderr)
        uninstall(desktop)
        raise
    print("Installed and active now. No logout or restart needed.")
    print("Uninstall with ./uninstall.sh. Shortcut backup:", STATE)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("install", "uninstall", "status"):
        raise RuntimeError("Usage: tools/manage.py install|uninstall|status")
    if os.geteuid() == 0:
        raise RuntimeError("Run as your desktop user, without sudo")
    for tool in ("kpackagetool6", "kwriteconfig6", "kreadconfig6"):
        if not shutil.which(tool):
            raise RuntimeError("Missing dependency: " + tool)
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE_DIR / "install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        desktop = Desktop()
        if sys.argv[1] == "status":
            print("Loaded:", desktop.loaded(), "Saved shortcut backup:", STATE.exists())
            for suffix in BINDINGS:
                print(suffix, desktop.keys(own_action(suffix)))
        elif sys.argv[1] == "install":
            install(desktop)
        else:
            uninstall(desktop)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Error:", error, file=sys.stderr)
        sys.exit(1)
