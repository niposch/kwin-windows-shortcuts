// SPDX-License-Identifier: MIT
// Copyright (c) 2026 niposch
/* global workspace, registerShortcut */

var WindowsShortcuts = (function () {
    "use strict";

    var pendingRecall = null;
    var minimizing = false;

    function forgetRecall() { pendingRecall = null; }

    workspace.windowActivated.connect(function (window) {
        // KWin's focus fallback during our minimize is expected. A subsequent
        // deliberate focus change ends this one-step undo opportunity.
        if (pendingRecall && !minimizing && window !== pendingRecall.fallback) forgetRecall();
    });
    workspace.windowRemoved.connect(function (window) {
        if (pendingRecall && (window === pendingRecall.window || window === pendingRecall.fallback)) forgetRecall();
    });
    workspace.currentDesktopChanged.connect(forgetRecall);
    workspace.currentActivityChanged.connect(forgetRecall);

    function recallMinimized() {
        var recall = pendingRecall;
        forgetRecall();
        if (!recall || !recall.window.minimized || workspace.activeWindow !== recall.fallback) return false;
        recall.window.minimized = false;
        if (recall.window.minimized) return false; // Window rules can deny restoration.
        workspace.activeWindow = recall.window;
        return true;
    }

    function close(a, b) { return Math.abs(a - b) < 0.01; }

    // Read KWin's requested tile, rather than guessing from pixel dimensions.
    // This works with scaled outputs, custom split sizes and pending configures.
    function tileState(window) {
        var tile = window.tile;
        if (!tile) return "none";
        var r = tile.relativeGeometry;
        if (!r) return "custom";
        var side = close(r.x, 0) && r.width <= 0.75 ? "left" :
            close(r.x + r.width, 1) && r.width <= 0.75 ? "right" : "";
        if (side && close(r.y, 0) && close(r.height, 1)) return side;
        if (side && close(r.y, 0) && close(r.height, 0.5)) return "top-" + side;
        if (side && close(r.y, 0.5) && close(r.height, 0.5)) return "bottom-" + side;
        return "custom";
    }

    function untileOnCurrentOutput(window) {
        var tile = window.tile;
        if (!tile) return;
        // Repeated side snapping can move the tile to a different output while
        // leaving the restore rectangle on the original one. Also, output may
        // still describe the previous committed frame during a rapid key chain.
        var geometry = tile.absoluteGeometry;
        var output = geometry ? workspace.screenAt({
            x: geometry.x + geometry.width / 2,
            y: geometry.y + geometry.height / 2
        }) : window.output;
        tile.unmanage(window);
        // Native migration translates the restored rectangle (and future
        // restore geometry) to this output, preserving size and window rules.
        if (output) workspace.sendClientToScreen(window, output);
    }

    function restore(window) {
        untileOnCurrentOutput(window);
        if (window.maximizeMode !== 0) window.setMaximize(false, false);
    }

    function half(window, side) {
        // Clear a corner first so KWin doesn't combine it with this half.
        restore(window);
        workspace[side === "left" ? "slotWindowQuickTileLeft" : "slotWindowQuickTileRight"]();
    }

    function handle(direction) {
        // Recall must run before the active-window guard: the last ordinary
        // window may have been minimized, leaving only the desktop focused.
        if (direction === "up" && recallMinimized()) return;
        if (direction !== "up") forgetRecall();
        var window = workspace.activeWindow;
        if (!window || window.specialWindow || window.fullScreen || window.move || window.resize) return;
        if (direction === "monitor-left" || direction === "monitor-right") {
            if (window.moveableAcrossScreens) {
                workspace[direction === "monitor-left" ? "slotWindowToLeftScreen" : "slotWindowToRightScreen"]();
            }
            return;
        }
        var state = tileState(window);
        if (direction === "left" || direction === "right") {
            if (window.resizeable && window.moveable) {
                workspace[direction === "left" ? "slotWindowQuickTileLeft" : "slotWindowQuickTileRight"]();
            }
        } else if (direction === "up") {
            if (!window.maximizable) return;
            if (state === "left" || state === "right") {
                workspace[state === "left" ? "slotWindowQuickTileTopLeft" : "slotWindowQuickTileTopRight"]();
            } else if (state === "bottom-left" || state === "bottom-right") {
                half(window, state.slice(7));
            } else {
                untileOnCurrentOutput(window);
                // Idempotent: holding Up on a maximized window never restores it.
                window.setMaximize(true, true);
            }
        } else if (direction === "down") {
            if (state === "top-left" || state === "top-right") {
                half(window, state.slice(4));
            } else if (state === "left" || state === "right") {
                workspace[state === "left" ? "slotWindowQuickTileBottomLeft" : "slotWindowQuickTileBottomRight"]();
            } else if (window.tile || window.maximizeMode !== 0) {
                restore(window);
            } else if (window.minimizable) {
                minimizing = true;
                try {
                    pendingRecall = { window: window, fallback: null };
                    window.minimized = true;
                    if (window.minimized && pendingRecall) pendingRecall.fallback = workspace.activeWindow;
                    else forgetRecall();
                } finally {
                    minimizing = false;
                }
            }
        }
    }

    var bindings = [
        ["Left", "Meta+Left", "left"], ["Right", "Meta+Right", "right"],
        ["Up", "Meta+Up", "up"], ["Down", "Meta+Down", "down"],
        ["MonitorLeft", "Meta+Shift+Left", "monitor-left"],
        ["MonitorRight", "Meta+Shift+Right", "monitor-right"]
    ];
    bindings.forEach(function (binding) {
        registerShortcut("WindowsShortcuts" + binding[0], "Windows-style " + binding[2],
            binding[1], function () { handle(binding[2]); });
    });
    return { handle: handle, tileState: tileState };
})();
