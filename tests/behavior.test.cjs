// SPDX-License-Identifier: MIT
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(require('node:path').join(__dirname, '../package/contents/code/main.js'), 'utf8');

function environment(state = 'none', maximizeMode = 0) {
    const calls = [];
    const rects = {
        left: [0, 0, .5, 1], right: [.5, 0, .5, 1],
        'top-left': [0, 0, .5, .5], 'top-right': [.5, 0, .5, .5],
        'bottom-left': [0, .5, .5, .5], 'bottom-right': [.5, .5, .5, .5],
        custom: [.2, .2, .4, .4]
    };
    const window = {
        maximizeMode, specialWindow: false, fullScreen: false,
        moveable: true, resizeable: true, moveableAcrossScreens: true,
        maximizable: true, minimizable: true, minimized: false,
        setMaximize(v, h) { calls.push(['maximize', v, h]); this.maximizeMode = (v ? 2 : 0) | (h ? 1 : 0); }
    };
    function tile(name) {
        const r = rects[name];
        window.tile = r ? {
            relativeGeometry: {x: r[0], y: r[1], width: r[2], height: r[3]},
            unmanage(w) { assert.equal(w, window); calls.push(['restore-tile']); w.tile = null; }
        } : null;
        window.maximizeMode = 0;
    }
    tile(state);
    window.maximizeMode = maximizeMode;
    function signal() {
        const handlers = [];
        return { connect: callback => handlers.push(callback), emit: (...args) => handlers.forEach(callback => callback(...args)) };
    }
    const workspace = {
        activeWindow: window, windowActivated: signal(), windowRemoved: signal(),
        currentDesktopChanged: signal(), currentActivityChanged: signal()
    };
    for (const [method, name] of Object.entries({Left: 'left', Right: 'right', TopLeft: 'top-left',
        TopRight: 'top-right', BottomLeft: 'bottom-left', BottomRight: 'bottom-right'})) {
        workspace['slotWindowQuickTile' + method] = () => { calls.push(['tile', name]); tile(name); };
    }
    workspace.slotWindowToLeftScreen = () => calls.push(['monitor', 'left']);
    workspace.slotWindowToRightScreen = () => calls.push(['monitor', 'right']);
    const shortcuts = new Map();
    const context = vm.createContext({workspace, registerShortcut: (id, label, key, callback) => shortcuts.set(key, callback)});
    vm.runInContext(source, context);
    return {window, workspace, calls, shortcuts, script: context.WindowsShortcuts};
}

test('six usable default bindings', () => {
    const e = environment();
    assert.equal(e.shortcuts.size, 6);
    e.shortcuts.get('Meta+Up')();
    assert.equal(e.window.maximizeMode, 3);
    e.shortcuts.get('Meta+Down')();
    assert.equal(e.window.maximizeMode, 0);
    assert.equal(e.window.minimized, false);
    e.shortcuts.get('Meta+Down')();
    assert.equal(e.window.minimized, true);
});

for (const side of ['left', 'right']) {
    test(side + ' halves, corners and restoration', () => {
        const e = environment();
        e.script.handle(side);
        assert.equal(e.script.tileState(e.window), side);
        e.script.handle('up');
        assert.equal(e.script.tileState(e.window), 'top-' + side);
        e.script.handle('down');
        assert.equal(e.script.tileState(e.window), side);
        e.script.handle('down');
        assert.equal(e.script.tileState(e.window), 'bottom-' + side);
        e.script.handle('up');
        assert.equal(e.script.tileState(e.window), side);
        e.script.handle('down');
        e.script.handle('down');
        assert.equal(e.window.tile, null);
        assert.equal(e.window.minimized, false);
        e.script.handle('down');
        assert.equal(e.window.minimized, true);
    });
    test('upper ' + side + ' corner can maximize', () => {
        const e = environment('top-' + side);
        e.script.handle('up');
        assert.equal(e.window.tile, null);
        assert.equal(e.window.maximizeMode, 3);
    });
}

test('Up is idempotent when already maximized', () => {
    const e = environment('none', 3);
    for (let i = 0; i < 5; i++) e.script.handle('up');
    assert.equal(e.window.maximizeMode, 3);
    assert.equal(e.window.minimized, false);
});
test('partial maximization restores before minimizing', () => {
    for (const mode of [1, 2]) {
        const e = environment('none', mode);
        e.script.handle('down');
        assert.equal(e.window.maximizeMode, 0);
        assert.equal(e.window.minimized, false);
    }
});
test('custom tiles restore on Down and maximize on Up', () => {
    const down = environment('custom'); down.script.handle('down');
    assert.equal(down.window.tile, null);
    assert.equal(down.window.minimized, false);
    const up = environment('custom'); up.script.handle('up');
    assert.equal(up.window.tile, null);
    assert.equal(up.window.maximizeMode, 3);
});
test('resized split widths still classify as halves', () => {
    const e = environment('left');
    e.window.tile.relativeGeometry.width = .6;
    e.script.handle('up');
    assert.equal(e.script.tileState(e.window), 'top-left');
});
test('monitor shortcuts delegate to native state-preserving moves', () => {
    const e = environment('left');
    e.script.handle('monitor-right'); e.script.handle('monitor-left');
    assert.deepEqual(e.calls, [['monitor', 'right'], ['monitor', 'left']]);
    assert.equal(e.script.tileState(e.window), 'left');
});
test('no focused window and protected windows are ignored', () => {
    for (const property of ['specialWindow', 'fullScreen', 'move', 'resize']) {
        const e = environment(); e.window[property] = true;
        for (const direction of ['up', 'down', 'left', 'right', 'monitor-left']) e.script.handle(direction);
        assert.deepEqual(e.calls, []);
        assert.equal(e.window.minimized, false);
    }
    const e = environment(); e.workspace.activeWindow = null;
    assert.doesNotThrow(() => e.script.handle('up'));
});
test('window capabilities are respected', () => {
    const e = environment();
    for (const property of ['resizeable', 'maximizable', 'minimizable', 'moveableAcrossScreens']) e.window[property] = false;
    for (const direction of ['up', 'down', 'left', 'right', 'monitor-left']) e.script.handle(direction);
    assert.deepEqual(e.calls, []);
    assert.equal(e.window.minimized, false);
});

function minimizeWithFallback(e, fallback) {
    let minimized = false;
    Object.defineProperty(e.window, 'minimized', {
        get: () => minimized,
        set: value => {
            minimized = value;
            if (value) {
                e.workspace.activeWindow = fallback;
                e.workspace.windowActivated.emit(fallback);
            }
        }
    });
    e.script.handle('down');
    assert.equal(e.window.minimized, true);
    assert.equal(e.workspace.activeWindow, fallback);
}

test('Up recalls the script-minimized window without maximizing its focus fallback', () => {
    const e = environment();
    const fallback = environment().window;
    minimizeWithFallback(e, fallback);
    e.script.handle('up');
    assert.equal(e.window.minimized, false);
    assert.equal(e.window.maximizeMode, 0);
    assert.equal(e.workspace.activeWindow, e.window);
    assert.equal(fallback.maximizeMode, 0);
    e.script.handle('up');
    assert.equal(e.window.maximizeMode, 3);
});
test('Up can recall when no window remains focused', () => {
    const e = environment();
    minimizeWithFallback(e, null);
    e.script.handle('up');
    assert.equal(e.window.minimized, false);
    assert.equal(e.workspace.activeWindow, e.window);
});
test('a deliberate focus change cancels recall, even after switching back', () => {
    const e = environment();
    const fallback = environment().window;
    minimizeWithFallback(e, fallback);
    const other = environment().window;
    e.workspace.activeWindow = other; e.workspace.windowActivated.emit(other);
    e.workspace.activeWindow = fallback; e.workspace.windowActivated.emit(fallback);
    e.script.handle('up');
    assert.equal(e.window.minimized, true);
    assert.equal(fallback.maximizeMode, 3);
});
test('another arrow action cancels recall', () => {
    const e = environment();
    const fallback = environment().window;
    minimizeWithFallback(e, fallback);
    e.script.handle('monitor-right');
    e.script.handle('up');
    assert.equal(e.window.minimized, true);
    assert.equal(fallback.maximizeMode, 3);
});
test('closing the minimized window releases it before a subsequent Up', () => {
    const e = environment();
    const fallback = environment().window;
    minimizeWithFallback(e, fallback);
    e.workspace.windowRemoved.emit(e.window);
    Object.defineProperty(e.window, 'maximizeMode', {get: () => { throw new Error('closed window accessed'); }});
    e.script.handle('up');
    assert.equal(fallback.maximizeMode, 3);
});
test('desktop/activity changes cancel recall', () => {
    for (const name of ['currentDesktopChanged', 'currentActivityChanged']) {
        const e = environment();
        const fallback = environment().window;
        minimizeWithFallback(e, fallback);
        e.workspace[name].emit();
        e.script.handle('up');
        assert.equal(e.window.minimized, true);
        assert.equal(fallback.maximizeMode, 3);
    }
});
test('manual unminimization does not hijack Up on the fallback', () => {
    const e = environment();
    const fallback = environment().window;
    minimizeWithFallback(e, fallback);
    e.window.minimized = false;
    e.script.handle('up');
    assert.equal(e.workspace.activeWindow, fallback);
    assert.equal(fallback.maximizeMode, 3);
});
