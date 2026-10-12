#!/usr/bin/python3
"""Exercise persistent minimize/recall callbacks with only disposable Qt windows."""
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
app.setApplicationName("kwin-windows-shortcuts-recall-test")
desktop = Desktop()
token = uuid.uuid4().hex
plugin = "windows-shortcuts-recall-test-" + token
service = "org.kde.WindowsShortcutsRecallTest"
reports = []
windows = {}
commands = ["prepare", "down", "up", "switch", "inspect"]


def pump(seconds):
    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        app.processEvents()
        while context.pending():
            context.iteration(False)
        time.sleep(.01)


def report(connection, sender, path, interface, method, args, invocation):
    reports.append(json.loads(args.unpack()[0]))
    invocation.return_value(None)


node = Gio.DBusNodeInfo.new_for_xml('''<node><interface name="org.kde.WindowsShortcutsRecallTest">
<method name="Report"><arg type="s" direction="in"/></method></interface></node>''')
registration = desktop.bus.register_object("/Recall", node.interfaces[0], report, None, None)
result = desktop.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                      "RequestName", "(su)", (service, 4))[0]
if result != 1:
    raise RuntimeError("Another recall test is running")

for label in ("a", "b", "c"):
    window = QWidget()
    window.setWindowTitle("Recall test " + token + " " + label)
    window.resize(720, 480)
    window.show()
    windows[label] = window
pump(.5)

source = (ROOT / "package/contents/code/main.js").read_text()
source = source.replace("registerShortcut(", "smokeRegisterShortcut(")
prefix = "var smokeCallbacks = {}; function smokeRegisterShortcut(id, text, key, cb) { smokeCallbacks[key] = cb; }\n"
harness = '''
function findTest(label) {
    return workspace.windowList().filter(function(w) { return w.caption === "Recall test " + TOKEN + " " + label; })[0];
}
function describe(window) {
    if (!window) return null;
    var g = window.frameGeometry;
    return {minimized: window.minimized, max: window.maximizeMode, geometry: [g.x, g.y, g.width, g.height]};
}
function reportTest(error) {
    var active = workspace.activeWindow;
    var state = {error: error || null, active: active ? "external" : "none"};
    ["a", "b", "c"].forEach(function(label) {
        var window = findTest(label);
        state[label] = describe(window);
        if (window && active === window) state.active = label;
    });
    callDBus("org.kde.WindowsShortcutsRecallTest", "/Recall", "org.kde.WindowsShortcutsRecallTest", "Report", JSON.stringify(state));
}
["prepare", "down", "up", "switch", "inspect"].forEach(function(command) {
    // Empty sequences: these callbacks are reachable only through this test's
    // uniquely named D-Bus actions, never through physical keys.
    registerShortcut(PLUGIN + command, "Disposable recall test " + command, "", function() {
        try {
            var a = findTest("a"), b = findTest("b"), c = findTest("c");
            var active = workspace.activeWindow;
            if (command === "prepare") {
                if (!a || !b || !c) throw new Error("Test windows missing");
                [a, b, c].forEach(function(w) { w.minimized = false; w.setMaximize(false, false); });
                workspace.activeWindow = b;
                workspace.activeWindow = a;
            } else if (command === "switch") {
                workspace.activeWindow = c;
            } else if (command === "down" || command === "up") {
                if (active && active !== a && active !== b && active !== c) throw new Error("User changed focus; aborting test action");
                if (command === "down" && active !== a) throw new Error("Down requires test window A");
                smokeCallbacks[command === "down" ? "Meta+Down" : "Meta+Up"]();
            }
            reportTest();
        } catch (error) { reportTest(String(error)); }
    });
});
reportTest();
'''

with tempfile.TemporaryDirectory(prefix="kwin-recall-test-") as temp:
    path = Path(temp) / "recall.js"
    path.write_text(prefix + source + "\nvar TOKEN = " + json.dumps(token) + "; var PLUGIN = " + json.dumps(plugin) + ";\n" + harness)
    loaded = False
    try:
        script_id = desktop.scripting("loadScript", "(ss)", (str(path), plugin))[0]
        assert script_id >= 0
        loaded = True
        desktop.call("org.kde.KWin", f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run")
        for _ in range(100):
            pump(.02)
            if reports:
                break
        assert reports, "KWin test script did not start"

        def invoke(command):
            reports.clear()
            desktop.call("org.kde.kglobalaccel", "/component/kwin", "org.kde.kglobalaccel.Component",
                         "invokeShortcut", "(s)", (plugin + command,))
            for _ in range(100):
                pump(.02)
                if reports:
                    assert not reports[-1]["error"], reports[-1]
                    return reports[-1]
            raise RuntimeError("Test callback did not report")

        def step(command):
            invoke(command)
            pump(.2)
            return invoke("inspect")

        original = step("prepare")
        minimized = step("down")
        assert minimized["a"]["minimized"] and minimized["active"] == "b", minimized
        restored = step("up")
        assert not restored["a"]["minimized"] and restored["active"] == "a", restored
        assert restored["a"]["max"] == restored["b"]["max"] == 0, restored
        assert restored["a"]["geometry"] == original["a"]["geometry"], (original, restored)
        print("PASS Down -> automatic focus fallback -> Up restores A at its original size")
        maximized = step("up")
        assert maximized["a"]["max"] == 3 and maximized["b"]["max"] == 0, maximized
        print("PASS another Up maximizes A, leaving fallback B unchanged")
        step("prepare")
        step("down")
        step("switch")
        switched = step("up")
        assert switched["a"]["minimized"] and switched["c"]["max"] == 3, switched
        print("PASS deliberate focus change cancels recall; Up acts on C")
        step("prepare")
        step("down")
        windows["a"].close()
        pump(.2)
        closed = step("up")
        assert closed["a"] is None and closed["b"]["max"] == 3, closed
        print("PASS closed recall target is forgotten safely")
        print("Persistent live recall tests passed.")
    finally:
        if loaded:
            desktop.scripting("unloadScript", "(s)", (plugin,))
            pump(.05)
        for command in commands:
            desktop.accel("unregister", "(ss)", ("kwin", plugin + command))
        for window in windows.values():
            window.close()
        pump(.1)
        desktop.bus.unregister_object(registration)
