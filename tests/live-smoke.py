#!/usr/bin/python3
"""Optional live test: moves only its own disposable Qt window; no real key injection."""
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

from gi.repository import Gio, GLib
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from manage import Desktop

app = QApplication([])
app.setApplicationName("kwin-windows-shortcuts-smoke")
desktop = Desktop()
title = "Windows shortcuts smoke " + uuid.uuid4().hex
probe_name = "windows-shortcuts-smoke-" + uuid.uuid4().hex
service = "org.kde.WindowsShortcutsSmoke"
reports = []


def report(connection, sender, path, interface, method, args, invocation):
    reports.append(json.loads(args.unpack()[0]))
    invocation.return_value(None)


node = Gio.DBusNodeInfo.new_for_xml('''<node><interface name="org.kde.WindowsShortcutsSmoke">
<method name="Report"><arg type="s" direction="in"/></method></interface></node>''')
registration = desktop.bus.register_object("/Smoke", node.interfaces[0], report, None, None)
reply = desktop.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                     "RequestName", "(su)", (service, 4))[0]
if reply != 1:
    raise RuntimeError("Another smoke test is running")


def pump(seconds):
    until = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < until:
        app.processEvents()
        while context.pending():
            context.iteration(False)
        time.sleep(.01)


source = (ROOT / "package/contents/code/main.js").read_text()
# Execute the actual handler callbacks in KWin, but keep test registrations local.
# No test shortcut can activate on a user's application.
source = source.replace("registerShortcut(", "smokeRegisterShortcut(")
prefix = "var smokeCallbacks = {}; function smokeRegisterShortcut(id, text, key, cb) { smokeCallbacks[key] = cb; }\n"
window = QWidget()
window.setWindowTitle(title)
window.resize(720, 480)
window.show()
pump(.5)

keys = {"up": "Meta+Up", "down": "Meta+Down", "left": "Meta+Left", "right": "Meta+Right",
        "monitor-left": "Meta+Shift+Left", "monitor-right": "Meta+Shift+Right"}

with tempfile.TemporaryDirectory(prefix="kwin-shortcuts-smoke-") as temp:
    path = Path(temp) / "probe.js"

    def probe(action=None, reset=False):
        reports.clear()
        body = '''
var target = workspace.windowList().filter(function(w) { return w.caption === TITLE; })[0];
if (!target) throw new Error("Disposable test window not found");
var previous = workspace.activeWindow;
if (ACTION || RESET) {
    workspace.activeWindow = target;
    if (RESET) {
        target.minimized = false;
        if (target.tile) target.tile.unmanage(target);
        target.setMaximize(false, false);
    }
    if (ACTION === "place-rightmost" || ACTION === "place-leftmost") {
        var sorted = workspace.screens.slice().sort(function(a, b) { return a.geometry.x - b.geometry.x; });
        workspace.sendClientToScreen(target, ACTION === "place-rightmost" ? sorted[sorted.length - 1] : sorted[0]);
    } else if (ACTION) smokeCallbacks[ACTION]();
    if (previous && previous !== target) workspace.activeWindow = previous;
}
var g = target.frameGeometry;
var result = {state: WindowsShortcuts.tileState(target), max: target.maximizeMode,
    minimized: target.minimized, output: target.output.name,
    geometry: [g.x, g.y, g.width, g.height]};
callDBus("org.kde.WindowsShortcutsSmoke", "/Smoke", "org.kde.WindowsShortcutsSmoke", "Report", JSON.stringify(result));
'''
        header = "var TITLE = " + json.dumps(title) + "; var ACTION = " + json.dumps(keys.get(action, action)) + "; var RESET = " + json.dumps(reset) + ";\n"
        path.write_text(prefix + source + header + body)
        sid = desktop.scripting("loadScript", "(ss)", (str(path), probe_name))[0]
        assert sid >= 0
        try:
            desktop.call("org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run")
            for _ in range(100):
                pump(.02)
                if reports:
                    return reports[-1]
            raise RuntimeError("KWin test did not report; inspect script errors")
        finally:
            desktop.scripting("unloadScript", "(s)", (probe_name,))
            pump(.04)

    def step(action):
        probe(action)
        pump(.2)
        return probe()

    def expect(action, state, max_mode=0, minimized=False, output=None):
        r = step(action)
        deadline = time.monotonic() + 2
        def matches():
            return ((r["state"], r["max"], r["minimized"]) == (state, max_mode, minimized)
                    and (output is None or r["output"] == output))
        # Window configure acknowledgments can arrive after the action's D-Bus
        # report, especially for Xwayland. Poll state without replaying the key.
        while not matches() and time.monotonic() < deadline:
            pump(.05)
            r = probe()
        assert matches(), (action, r)
        print("PASS", action, state, "max=" + str(max_mode), "minimized=" + str(minimized))
        return r

    try:
        original = probe()
        expect("up", "none", 3)
        expect("up", "none", 3)
        restored = expect("down", "none")
        assert restored["geometry"] == original["geometry"], (original, restored)
        expect("down", "none", minimized=True)
        probe(reset=True)
        pump(.2)
        for side in ("left", "right"):
            expect(side, side)
            expect("up", "top-" + side)
            expect("down", side)
            expect("down", "bottom-" + side)
            expect("up", side)
            expect("up", "top-" + side)
            expect("up", "none", 3)
            expect("down", "none")
            expect(side, side)
            expect("down", "bottom-" + side)
            restored = expect("down", "none")
            assert restored["geometry"] == original["geometry"], (original, restored)
        # Repeated side snapping crosses outputs through a different KWin path
        # than Shift+arrows and can retain an older tile restore rectangle.
        for direction, opposite, placement in [("left", "right", "place-rightmost"), ("right", "left", "place-leftmost")]:
            probe(reset=True)
            pump(.2)
            step(placement)
            expect(direction, direction)
            origin = probe()
            crossed = step(direction)
            if crossed["output"] == origin["output"]:
                print("SKIP repeated-snap test: no adjacent output")
                continue
            assert crossed["state"] == opposite, crossed
            for action, state, max_mode in [
                ("up", "top-" + opposite, 0), ("down", opposite, 0),
                ("down", "bottom-" + opposite, 0), ("up", opposite, 0),
                ("up", "top-" + opposite, 0), ("up", "none", 3), ("down", "none", 0)
            ]:
                result = expect(action, state, max_mode, output=crossed["output"])
                assert result["output"] == crossed["output"], (crossed, result)
            print("PASS repeated", direction, "crossing: all untile/maximize/restore transitions stay on target")
        before = probe()
        left = step("monitor-left")
        if left["output"] != before["output"]:
            expect("left", "left")
            snapped = probe()
            moved = expect("monitor-right", "left")
            assert moved["output"] != snapped["output"], (snapped, moved)
            target_output = moved["output"]
            quarter = expect("up", "top-left", output=target_output)
            assert quarter["output"] == target_output, (moved, quarter)
            maximized_on_target = expect("up", "none", 3, output=target_output)
            assert maximized_on_target["output"] == target_output, (moved, maximized_on_target)
            maximized = probe()
            moved = expect("monitor-left", "none", 3)
            assert moved["output"] != maximized["output"], (maximized, moved)
            print("PASS monitor moves preserve half-tile and maximization")
        else:
            print("SKIP monitor test: no output to the left of the test window")
        print("Live smoke passed; only the disposable window was moved.")
    finally:
        window.close()
        pump(.1)
        desktop.bus.unregister_object(registration)
