# -*- coding: utf-8 -*-
"""
Direct framebuffer + touch backend for the AZ-Touch Pi0 (ILI9341).

Why this exists
---------------
On this Raspberry Pi OS build, SDL's display drivers (fbcon, kmsdrm,
directfb) are NOT available, so pygame cannot open the TFT directly.
But the display IS a standard Linux framebuffer at /dev/fb0 in 16-bit
RGB565 format (confirmed: bits_per_pixel=16, virtual_size=320,240).

So we let pygame render onto an OFF-SCREEN surface (using the always-
available "dummy" video driver) and then copy that surface to /dev/fb0
ourselves, converting 32-bit RGB to 16-bit RGB565. Touch is read straight
from the kernel input device via evdev.

This module degrades gracefully:
  * If /dev/fb0 is missing, FrameBuffer.available is False.
  * If evdev / the touch device is missing, touch just yields nothing.
"""

import os
import struct
import sys

import pygame

import config


# ---------------------------------------------------------------------------
# Framebuffer writer
# ---------------------------------------------------------------------------
class FrameBuffer:
    def __init__(self, device="/dev/fb0"):
        self.device = device
        self.available = os.path.exists(device)
        self.width = config.SCREEN_W
        self.height = config.SCREEN_H
        self._fb = None
        self._line_length = self.width * 2  # 2 bytes/pixel (RGB565)

        # Read real geometry from sysfs if present (robust to rotation).
        try:
            base = "/sys/class/graphics/fb0"
            with open(f"{base}/virtual_size") as f:
                w, h = f.read().strip().split(",")
                self.width, self.height = int(w), int(h)
            with open(f"{base}/stride") as f:
                self._line_length = int(f.read().strip())
        except Exception:
            # stride file may not exist; assume packed width*2
            self._line_length = self.width * 2

        if self.available:
            try:
                self._fb = open(device, "wb")
            except Exception as exc:
                print(f"[fb] cannot open {device}: {exc}", file=sys.stderr)
                self.available = False

    def blit(self, surface):
        """Convert a pygame Surface to RGB565 and write it to /dev/fb0."""
        if not self.available or self._fb is None:
            return
        # Ensure the surface matches the framebuffer size.
        if surface.get_size() != (self.width, self.height):
            surface = pygame.transform.scale(surface, (self.width, self.height))
        data = _surface_to_rgb565(surface)
        try:
            self._fb.seek(0)
            self._fb.write(data)
            self._fb.flush()
        except Exception as exc:
            print(f"[fb] write failed: {exc}", file=sys.stderr)

    def close(self):
        if self._fb:
            try:
                self._fb.close()
            except Exception:
                pass


def _surface_to_rgb565(surface):
    """
    Convert a pygame Surface to little-endian RGB565 bytes in row-major
    (height, width) order, as the Linux framebuffer expects.

    Fast path uses numpy; if numpy is unavailable, falls back to a slow
    pure-Python loop (only suitable for occasional use).
    """
    try:
        import numpy as np
        import pygame.surfarray as surfarray
        # array3d is (width, height, 3); transpose to (height, width, 3).
        a = surfarray.array3d(surface).transpose(1, 0, 2).astype(np.uint16)
        r = (a[:, :, 0] >> 3)
        g = (a[:, :, 1] >> 2)
        b = (a[:, :, 2] >> 3)
        rgb565 = (r << 11) | (g << 5) | b
        return rgb565.astype("<u2").tobytes()
    except Exception:
        return _to_rgb565(surface)


def _to_rgb565(surface):
    """Manual RGB888 -> RGB565 fallback (slow, only if numpy is missing)."""
    raw = pygame.image.tostring(surface, "RGB")
    out = bytearray(len(raw) // 3 * 2)
    j = 0
    for i in range(0, len(raw), 3):
        r = raw[i] >> 3
        g = raw[i + 1] >> 2
        b = raw[i + 2] >> 3
        val = (r << 11) | (g << 5) | b
        out[j] = val & 0xFF
        out[j + 1] = (val >> 8) & 0xFF
        j += 2
    return bytes(out)


# ---------------------------------------------------------------------------
# Touch reader (evdev)
# ---------------------------------------------------------------------------
class Touch:
    """
    Reads absolute touch coordinates from a kernel input device.

    Emits simple events via poll(): a list of ("down"/"up"/"move", x, y).
    Calibration is linear, configured by the min/max raw ranges below.
    """

    def __init__(self):
        self.available = False
        self._dev = None
        self._x_raw = None
        self._y_raw = None
        self._touching = False
        self._pending = []

        # Raw ADC range of the XPT2046 (typical). Adjust if calibration is off.
        self.RAW_MIN_X = getattr(config, "TOUCH_MIN_X", 200)
        self.RAW_MAX_X = getattr(config, "TOUCH_MAX_X", 3900)
        self.RAW_MIN_Y = getattr(config, "TOUCH_MIN_Y", 200)
        self.RAW_MAX_Y = getattr(config, "TOUCH_MAX_Y", 3900)
        self.SWAP_XY = getattr(config, "TOUCH_SWAP_XY", True)
        self.INVERT_X = getattr(config, "TOUCH_INVERT_X", False)
        self.INVERT_Y = getattr(config, "TOUCH_INVERT_Y", True)

        try:
            from evdev import InputDevice, list_devices, ecodes
            self._ecodes = ecodes
            dev_path = self._find_touch_device(InputDevice, list_devices, ecodes)
            if dev_path:
                self._dev = InputDevice(dev_path)
                self._dev.grab() if False else None  # don't grab; share is fine
                os.set_blocking(self._dev.fd, False)
                self.available = True
                print(f"[touch] using {dev_path} ({self._dev.name})")
            else:
                print("[touch] no touchscreen device found", file=sys.stderr)
        except Exception as exc:
            print(f"[touch] evdev not available: {exc}", file=sys.stderr)

    def _find_touch_device(self, InputDevice, list_devices, ecodes):
        for path in list_devices():
            try:
                d = InputDevice(path)
                caps = d.capabilities()
                if ecodes.EV_ABS in caps:
                    name = (d.name or "").lower()
                    if any(k in name for k in ("touch", "ads7846", "xpt", "stmpe")):
                        return path
                    # otherwise, any ABS device with X and Y is a candidate
                    abs_codes = [c for c, _ in caps.get(ecodes.EV_ABS, [])]
                    if ecodes.ABS_X in abs_codes and ecodes.ABS_Y in abs_codes:
                        return path
            except Exception:
                continue
        return None

    def poll(self):
        """Return a list of (kind, x, y) events since last poll."""
        if not self.available or self._dev is None:
            return []
        ec = self._ecodes
        try:
            for event in self._dev.read():
                if event.type == ec.EV_ABS:
                    if event.code in (ec.ABS_X, getattr(ec, "ABS_MT_POSITION_X", -1)):
                        self._x_raw = event.value
                    elif event.code in (ec.ABS_Y, getattr(ec, "ABS_MT_POSITION_Y", -1)):
                        self._y_raw = event.value
                elif event.type == ec.EV_KEY and event.code == ec.BTN_TOUCH:
                    if event.value == 1:
                        self._touching = True
                        xy = self._map()
                        if xy:
                            self._pending.append(("down", xy[0], xy[1]))
                    elif event.value == 0:
                        self._touching = False
                        xy = self._map()
                        if xy:
                            self._pending.append(("up", xy[0], xy[1]))
                elif event.type == ec.EV_SYN:
                    if self._touching:
                        xy = self._map()
                        if xy:
                            self._pending.append(("move", xy[0], xy[1]))
        except BlockingIOError:
            pass
        except Exception:
            pass
        out, self._pending = self._pending, []
        return out

    def _map(self):
        if self._x_raw is None or self._y_raw is None:
            return None

        # Decide which raw axis drives horizontal vs vertical.
        if self.SWAP_XY:
            raw_h, raw_v = self._y_raw, self._x_raw
            h_lo, h_hi = self.RAW_MIN_Y, self.RAW_MAX_Y
            v_lo, v_hi = self.RAW_MIN_X, self.RAW_MAX_X
        else:
            raw_h, raw_v = self._x_raw, self._y_raw
            h_lo, h_hi = self.RAW_MIN_X, self.RAW_MAX_X
            v_lo, v_hi = self.RAW_MIN_Y, self.RAW_MAX_Y

        def norm(v, lo, hi):
            if hi == lo:
                return 0.0
            return max(0.0, min(1.0, (v - lo) / float(hi - lo)))

        nx = norm(raw_h, h_lo, h_hi)
        ny = norm(raw_v, v_lo, v_hi)
        if self.INVERT_X:
            nx = 1.0 - nx
        if self.INVERT_Y:
            ny = 1.0 - ny

        x = int(nx * (config.SCREEN_W - 1))
        y = int(ny * (config.SCREEN_H - 1))
        return (x, y)

    def close(self):
        if self._dev:
            try:
                self._dev.close()
            except Exception:
                pass
