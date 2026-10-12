// SPDX-License-Identifier: MIT
// Copyright (c) 2026 niposch
/* global workspace, registerShortcut */

var WindowsShortcuts = (function () {
    "use strict";

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

    function restore(window) {
        if (window.tile) window.tile.unmanage(window);
        if (window.maximizeMode !== 0) window.setMaximize(false, false);
    }

    function half(window, side) {
        // Clear a corner first so KWin doesn't combine it with this half.
        restore(window);
        workspace[side === "left" ? "slotWindowQuickTileLeft" : "slotWindowQuickTileRight"]();
    }

    function handle(direction) {
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
                if (window.tile) window.tile.unmanage(window);
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
                window.minimized = true;
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
