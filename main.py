#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Air quality monitoring station - main application.

Three swipeable screens on a 320x240 touch display:
  1. Craiova (always)         - all data, PM highlighted
  2. Local vs OpenAQ          - SDS011 sensor compared to city average
  3. Search                   - pick another city, view its data

Display backend
---------------
On the Raspberry Pi the TFT is a raw Linux framebuffer (/dev/fb0, RGB565)
and SDL has no usable display driver, so we render with pygame onto an
off-screen surface and copy it to /dev/fb0 ourselves (see fb_display.py).
Touch comes from evdev. On a PC (--windowed) we use a normal SDL window
and the mouse, for development.

Usage:
  python3 main.py            # Pi: framebuffer + touch (auto-detected)
  python3 main.py --windowed # PC: desktop window + mouse (for testing)
"""

import os
import sys
import time

import config
from data_manager import DataManager
from mqtt_client import MqttSensor

# Height (px) of the bottom navigation bar with the prev/next arrows.
NAV_H = 40


def _looks_like_pi():
    try:
        with open("/proc/cpuinfo") as f:
            return "Raspberry" in f.read()
    except Exception:
        return False


class App:
    def __init__(self, force_windowed=False):
        self.windowed = force_windowed or not _looks_like_pi()

        if not self.windowed:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

        import pygame
        self.pygame = pygame
        pygame.init()
        pygame.mouse.set_visible(False)

        if self.windowed:
            pygame.display.init()
            self.window = pygame.display.set_mode(
                (config.SCREEN_W, config.SCREEN_H))
            pygame.display.set_caption("Air Quality Station (dev)")
            self.surface = self.window
            self.fb = None
            self.touch = None
        else:
            pygame.display.init()
            pygame.display.set_mode((config.SCREEN_W, config.SCREEN_H))
            self.surface = pygame.Surface((config.SCREEN_W, config.SCREEN_H))
            from fb_display import FrameBuffer, Touch
            self.fb = FrameBuffer("/dev/fb0")
            self.touch = Touch()
            if not self.fb.available:
                print("[main] /dev/fb0 not writable. Try: sudo python3 main.py",
                      file=sys.stderr)

        from screens import (Fonts, CraiovaScreen, CompareScreen,
                             SearchScreen, draw_page_dots, draw_text)
        self._draw_page_dots = draw_page_dots
        self._draw_text = draw_text
        self.fonts = Fonts()

        self.data = DataManager()
        self.sensor = MqttSensor()

        self.screens = [
            CraiovaScreen(self),
            CompareScreen(self),
            SearchScreen(self),
        ]
        self.SearchScreen = SearchScreen
        self.index = 0

        self._press_pos = None
        self._press_time = 0

        self._running = True

    def start_services(self):
        self.data.start()
        self.sensor.start()

    def _on_pointer_down(self, pos):
        self._press_pos = pos
        self._press_time = time.time()

    def _on_pointer_up(self, pos):
        # Treat as a tap if the finger barely moved and it was quick.
        if self._press_pos is None:
            return
        dx = abs(pos[0] - self._press_pos[0])
        dy = abs(pos[1] - self._press_pos[1])
        dt = time.time() - self._press_time
        self._press_pos = None
        if dx < 18 and dy < 18 and dt < 1.0:
            self._handle_tap(pos)

    def _handle_tap(self, pos):
        x, y = pos
        # Bottom navigation bar: left third = prev, right third = next.
        if y >= config.SCREEN_H - NAV_H:
            if x < config.SCREEN_W * 0.33:
                self._go(self.index - 1)
            elif x > config.SCREEN_W * 0.67:
                self._go(self.index + 1)
            return
        # Otherwise the active screen handles the tap.
        self.screens[self.index].handle_tap(pos)

    def _go(self, new_index):
        new_index = max(0, min(len(self.screens) - 1, new_index))
        if new_index != self.index:
            self.index = new_index
        self._dirty = True

    def run(self):
        pygame = self.pygame
        self.start_services()

        self._dirty = True            # needs an initial draw
        last_periodic = 0.0           # last forced redraw (clock/freshness)
        last_data_sig = None          # detect background data changes

        while self._running:
            now = time.time()

            # --- input ---
            if self.windowed:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self._running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            self._running = False
                        elif event.key == pygame.K_LEFT:
                            self._go(self.index - 1)
                        elif event.key == pygame.K_RIGHT:
                            self._go(self.index + 1)
                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        self._on_pointer_down(event.pos)
                    elif event.type == pygame.MOUSEBUTTONUP:
                        self._on_pointer_up(event.pos); self._dirty = True
            else:
                pygame.event.pump()
                if self.touch:
                    for kind, x, y in self.touch.poll():
                        if kind == "down":
                            self._on_pointer_down((x, y))
                        elif kind == "up":
                            self._on_pointer_up((x, y)); self._dirty = True

            # --- redraw periodically for the "x min ago" freshness text ---
            if now - last_periodic >= 10.0:
                last_periodic = now
                self._dirty = True

            # --- redraw if background data changed ---
            sig = self._data_signature()
            if sig != last_data_sig:
                last_data_sig = sig
                self._dirty = True

            # --- render only when needed ---
            if self._dirty:
                self._render()
                self._dirty = False

            # Idle sleep: keeps touch latency low (~20 ms) but CPU near zero.
            time.sleep(0.02)

        self._shutdown()

    def _data_signature(self):
        """A cheap fingerprint of displayed data, to detect changes."""
        try:
            c = self.data.get_craiova()
            parts = [self.index, c.ok, c.updated_ts, len(c.values)]
            r = self.sensor.get_reading() if self.sensor else None
            if r is not None:
                parts += [r.pm25, r.pm10, round(r.ts)]
            s = self.data.get_search()
            if s is not None:
                parts += [s.ok, len(s.values), s.location_name]
            return tuple(parts)
        except Exception:
            return None

    def _render(self):
        surf = self.surface
        surf.fill(config.COL_BG)

        # Draw the active screen.
        self.screens[self.index].draw(surf)

        # Bottom navigation bar with prev/next arrows + page dots.
        self._draw_nav_bar(surf)

        if self.windowed:
            self.pygame.display.flip()
        elif self.fb:
            self.fb.blit(surf)

    def _draw_nav_bar(self, surf):
        pygame = self.pygame
        W, H = config.SCREEN_W, config.SCREEN_H
        bar_y = H - NAV_H
        # divider line, nudged down a bit so it sits closer to the arrows
        line_y = bar_y + 8
        pygame.draw.line(surf, config.COL_DIVIDER, (10, line_y),
                         (W - 10, line_y), 1)
        cy = bar_y + NAV_H // 2 + 4

        # left arrow (dim if on first screen)
        left_col = (config.COL_ACCENT if self.index > 0
                    else config.COL_TEXT_FAINT)
        self._draw_text(surf, self.fonts.med, "\u2039", left_col,
                        int(W * 0.16), cy, anchor="center")

        # right arrow (dim if on last screen)
        right_col = (config.COL_ACCENT if self.index < len(self.screens) - 1
                     else config.COL_TEXT_FAINT)
        self._draw_text(surf, self.fonts.med, "\u203a", right_col,
                        int(W * 0.84), cy, anchor="center")

        # page dots in the centre
        gap = 16
        start = W // 2 - (len(self.screens) - 1) * gap // 2
        for i in range(len(self.screens)):
            col = config.COL_ACCENT if i == self.index else config.COL_TEXT_FAINT
            pygame.draw.circle(surf, col, (start + i * gap, cy), 3)

    def _shutdown(self):
        self.data.stop()
        self.sensor.stop()
        if self.fb:
            self.fb.close()
        if self.touch:
            self.touch.close()
        self.pygame.quit()


def main():
    force_windowed = "--windowed" in sys.argv
    app = App(force_windowed=force_windowed)
    app.run()


if __name__ == "__main__":
    main()
