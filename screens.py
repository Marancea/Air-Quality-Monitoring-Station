# -*- coding: utf-8 -*-
"""
User interface: three screens drawn with Pygame on a 240x320 PORTRAIT display.

Screen 1 (Craiova):   temperature banner + a uniform card per pollutant,
                      with the overall AQI; PM2.5/PM10 lead the list.
Screen 2 (Compare):   local SDS011 sensor vs OpenAQ Craiova average.
Screen 3 (Search):    pick another city from a list, show its data.

Navigation: swipe up/down inside lists; swipe left/right to change screen.
"""

import time

import pygame

import config
import aqi


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
class Fonts:
    def __init__(self):
        def load(size, bold=False):
            try:
                path = pygame.font.match_font("dejavusans", bold=bold)
                if path:
                    return pygame.font.Font(path, size)
            except Exception:
                pass
            return pygame.font.Font(None, size)

        self.huge = load(54, bold=True)
        self.big = load(30, bold=True)
        self.medbig = load(26, bold=True)
        self.med = load(23, bold=True)
        self.reg = load(19)
        self.small = load(16)
        self.tiny = load(13)


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def draw_text(surf, font, text, color, x, y, anchor="topleft"):
    img = font.render(str(text), True, color)
    rect = img.get_rect()
    setattr(rect, anchor, (x, y))
    surf.blit(img, rect)
    return rect


def rounded_rect(surf, color, rect, radius=8):
    pygame.draw.rect(surf, color, rect, border_radius=radius)


def fmt(value, decimals=1):
    if value is None:
        return "--"
    return f"{value:.{decimals}f}"


class Screen:
    def __init__(self, app):
        self.app = app
        self.fonts = app.fonts

    def draw(self, surf):
        raise NotImplementedError

    def handle_tap(self, pos):
        return False


# ---------------------------------------------------------------------------
# Shared chrome
# ---------------------------------------------------------------------------
def draw_header(surf, fonts, title, subtitle=None):
    draw_text(surf, fonts.med, title, config.COL_TEXT, 14, 10)
    if subtitle:
        draw_text(surf, fonts.tiny, subtitle, config.COL_TEXT_DIM,
                  config.SCREEN_W - 14, 17, anchor="topright")
    pygame.draw.line(surf, config.COL_DIVIDER, (14, 38),
                     (config.SCREEN_W - 14, 38), 1)


def draw_page_dots(surf, index, count):
    cx = config.SCREEN_W // 2
    y = config.SCREEN_H - 12
    gap = 16
    start = cx - (count - 1) * gap // 2
    for i in range(count):
        col = config.COL_ACCENT if i == index else config.COL_TEXT_FAINT
        pygame.draw.circle(surf, col, (start + i * gap, y), 3)


def _param_color(param, value):
    si = aqi.sub_index(param, value)
    cat = aqi.aqi_category(si)
    return config.AQI_COLORS[cat] if cat is not None else config.COL_TEXT_DIM


def draw_text_fit(surf, fonts, text, color, x, y, max_w, max_h=None,
                  prefer="big"):
    """Draw text, shrinking the font so it fits within max_w (and max_h)."""
    order = ["big", "medbig", "med", "reg", "small", "tiny"]
    start = order.index(prefer) if prefer in order else 0
    for name in order[start:]:
        f = getattr(fonts, name)
        w_ok = f.size(str(text))[0] <= max_w
        h_ok = (max_h is None) or (f.get_height() <= max_h)
        if w_ok and h_ok:
            return draw_text(surf, f, text, color, x, y)
    return draw_text(surf, fonts.tiny, text, color, x, y)


def pollutant_card(surf, fonts, param, value, n, x, y, w, h):
    """A uniform card: accent bar, label + count on top row, big value below.

    Units are omitted per-card (they are all ug/m3) and noted once on the
    screen footer, which keeps these narrow cards clean and collision-free.
    The value auto-shrinks if it would otherwise overflow the card.
    """
    label, _unit = config.PARAM_LABELS[param]
    rect = pygame.Rect(x, y, w, h)
    rounded_rect(surf, config.COL_BG_CARD, rect, radius=10)
    accent = _param_color(param, value)
    pygame.draw.rect(surf, accent, pygame.Rect(x, y, 5, h),
                     border_top_left_radius=10, border_bottom_left_radius=10)
    # compact label row (small) + contributor count
    draw_text(surf, fonts.tiny, label, config.COL_TEXT_DIM, x + 14, y + 5)
    if n:
        draw_text(surf, fonts.tiny, f"x{n}", config.COL_TEXT_FAINT,
                  x + w - 8, y + 5, anchor="topright")
    # value auto-fits the remaining card space (width AND height) so it
    # never spills past the card edges, even for big numbers like CO.
    val_y = y + 21
    draw_text_fit(surf, fonts, fmt(value, 1), config.COL_TEXT,
                  x + 14, val_y, max_w=w - 20, max_h=h - val_y + y - 3,
                  prefer="med")


def aqi_badge(surf, fonts, aqi_value, x, y, w, h):
    cat = aqi.aqi_category(aqi_value)
    color = config.AQI_COLORS[cat] if cat is not None else config.COL_BG_CARD_HI
    label = config.AQI_LABELS[cat] if cat is not None else "No data"
    rounded_rect(surf, color, pygame.Rect(x, y, w, h), radius=10)
    val_txt = str(aqi_value) if aqi_value is not None else "--"
    txtcol = (20, 20, 20) if cat in (0, 1, 2) else (245, 245, 245)
    draw_text(surf, fonts.tiny, "AQI", txtcol, x + 10, y + 8)
    draw_text(surf, fonts.med, val_txt, txtcol, x + w - 12, y + 6,
              anchor="topright")
    draw_text(surf, fonts.tiny, label, txtcol, x + w // 2, y + h - 17,
              anchor="midtop")


# ---------------------------------------------------------------------------
# Screen 1 - Craiova (portrait)
# ---------------------------------------------------------------------------
class CraiovaScreen(Screen):
    def draw(self, surf):
        data = self.app.data.get_craiova()
        draw_header(surf, self.fonts, "Craiova", self._fresh(data))

        if not data.ok:
            draw_text(surf, self.fonts.reg, "Waiting for data...",
                      config.COL_TEXT_DIM, config.SCREEN_W // 2, 150,
                      anchor="center")
            draw_text(surf, self.fonts.tiny, "Check API key / network",
                      config.COL_TEXT_FAINT, config.SCREEN_W // 2, 174,
                      anchor="center")
            return

        # --- Top banner: temperature + AQI, side by side ---
        self._weather_banner(surf, data, 14, 46)

        aqi_value, dom = aqi.overall_aqi(data.values)
        aqi_badge(surf, self.fonts, aqi_value, 138, 46, 88, 62)

        # --- Pollutant cards: two columns, PM first ---
        x0, y0 = 14, 112
        cw, ch = 104, 52
        gx, gy = 8, 5
        for i, p in enumerate(config.PARAM_ORDER):
            col = i % 2
            row = i // 2
            x = x0 + col * (cw + gx)
            y = y0 + row * (ch + gy)
            pollutant_card(surf, self.fonts, p, data.values.get(p),
                           data.contributors.get(p), x, y, cw, ch)

    def _weather_banner(self, surf, data, x, y):
        rect = pygame.Rect(x, y, 116, 62)
        rounded_rect(surf, config.COL_BG_CARD, rect, radius=10)
        if data.temperature is not None:
            draw_text(surf, self.fonts.big, f"{data.temperature:.0f}",
                      config.COL_TEXT, x + 12, y + 8)
            w = self.fonts.big.size(f"{data.temperature:.0f}")[0]
            draw_text(surf, self.fonts.small, "C", config.COL_ACCENT,
                      x + 15 + w, y + 12)
        else:
            draw_text(surf, self.fonts.med, "--", config.COL_TEXT_DIM,
                      x + 12, y + 12)
        extra = []
        if data.humidity is not None:
            extra.append(f"{data.humidity:.0f}%")
        if data.wind is not None:
            extra.append(f"{data.wind:.0f}km/h")
        if extra:
            draw_text(surf, self.fonts.tiny, "  ".join(extra),
                      config.COL_TEXT_DIM, x + 12, rect.bottom - 16)

    def _fresh(self, data):
        if not data.ok or not data.updated_ts:
            return None
        age = int(time.time() - data.updated_ts)
        if age < 90:
            return "just now"
        if age < 3600:
            return f"{age // 60} min ago"
        return f"{age // 3600} h ago"



# ---------------------------------------------------------------------------
# Screen 2 - Comparison (portrait)
# ---------------------------------------------------------------------------
class CompareScreen(Screen):
    def draw(self, surf):
        draw_header(surf, self.fonts, "Local vs OpenAQ")
        api_data = self.app.data.get_craiova()
        reading = self.app.sensor.get_reading()

        # headers - two columns centered over their value areas
        # Mine column: x 70..150 ; OpenAQ column: x 154..226
        draw_text(surf, self.fonts.small, "Mine", config.COL_ACCENT, 110, 48,
                  anchor="midtop")
        draw_text(surf, self.fonts.small, "OpenAQ", config.COL_GOOD, 190, 48,
                  anchor="midtop")
        pygame.draw.line(surf, config.COL_DIVIDER, (14, 70),
                         (config.SCREEN_W - 14, 70), 1)

        self._row(surf, "PM2.5", reading.pm25 if reading else None,
                  api_data.values.get("pm25"), 82)
        self._row(surf, "PM10", reading.pm10 if reading else None,
                  api_data.values.get("pm10"), 134)

        # diff explanation cards
        self._diffbox(surf, "PM2.5", reading.pm25 if reading else None,
                      api_data.values.get("pm25"), 196)
        self._diffbox(surf, "PM10", reading.pm10 if reading else None,
                      api_data.values.get("pm10"), 232)

        if not self.app.sensor.available:
            status, col = "MQTT lib not installed", config.COL_WARN
        elif reading is None:
            status, col = "Waiting for sensor...", config.COL_TEXT_DIM
        elif not reading.is_fresh():
            status, col = "Sensor data stale", config.COL_WARN
        else:
            rssi = f"  RSSI {int(reading.rssi)}" if reading.rssi else ""
            status, col = f"Live{rssi}", config.COL_GOOD
        draw_text(surf, self.fonts.small, status, col, 14, 270)

    def _row(self, surf, label, local, api_val, y):
        # label on the far left
        draw_text(surf, self.fonts.small, label, config.COL_TEXT_DIM, 14, y + 6)
        # Mine value: fits within x 66..150 (84 px), right-aligned by centering
        draw_text_fit(surf, self.fonts, fmt(local, 1), config.COL_TEXT,
                      68, y, max_w=80, max_h=30, prefer="med")
        # OpenAQ value: fits within x 154..228 (74 px)
        draw_text_fit(surf, self.fonts, fmt(api_val, 1), config.COL_TEXT,
                      154, y, max_w=78, max_h=30, prefer="med")

    def _diffbox(self, surf, label, local, api_val, y):
        rect = pygame.Rect(14, y, config.SCREEN_W - 28, 32)
        rounded_rect(surf, config.COL_BG_CARD, rect, radius=8)
        draw_text(surf, self.fonts.small, label + " diff", config.COL_TEXT_DIM,
                  rect.x + 12, y + 8)
        if local is not None and api_val is not None:
            diff = local - api_val
            sign = "+" if diff >= 0 else ""
            dcol = config.COL_BAD if abs(diff) > 15 else config.COL_GOOD
            draw_text(surf, self.fonts.med, f"{sign}{diff:.0f}", dcol,
                      rect.right - 12, y + 5, anchor="topright")
        else:
            draw_text(surf, self.fonts.med, "--", config.COL_TEXT_FAINT,
                      rect.right - 12, y + 5, anchor="topright")


# ---------------------------------------------------------------------------
# Screen 3 - Search (portrait)
# ---------------------------------------------------------------------------
class SearchScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.selected = None
        self.scroll = 0
        self.rows_visible = 6
        self._list_rects = []
        self.mode = "list"

    def draw(self, surf):
        if self.mode == "detail":
            self._draw_detail(surf)
        else:
            self._draw_list(surf)

    def _draw_list(self, surf):
        draw_header(surf, self.fonts, "Search city")
        self._list_rects = []
        cities = config.PRESET_CITIES
        top = 46
        bottom_limit = config.SCREEN_H - 44   # leave room for nav bar
        n = len(cities)
        # Fit all cities between top and bottom_limit.
        row_h = max(22, (bottom_limit - top) // n)
        for idx in range(n):
            name = cities[idx][0]
            y = top + idx * row_h
            rect = pygame.Rect(14, y, config.SCREEN_W - 28, row_h - 4)
            rounded_rect(surf, config.COL_BG_CARD, rect, radius=8)
            draw_text(surf, self.fonts.reg, name, config.COL_TEXT,
                      rect.x + 14, rect.y + (rect.height - 19) // 2)
            self._list_rects.append((rect, idx))

    def _draw_detail(self, surf):
        busy = self.app.data.is_search_busy()
        data = self.app.data.get_search()
        # Back arrow (tappable) + city name as title.
        draw_text(surf, self.fonts.med, "\u2190", config.COL_ACCENT, 14, 10)
        draw_text(surf, self.fonts.med, self.selected or "City",
                  config.COL_TEXT, 44, 10)
        pygame.draw.line(surf, config.COL_DIVIDER, (14, 38),
                         (config.SCREEN_W - 14, 38), 1)

        if busy or data is None:
            draw_text(surf, self.fonts.reg, "Loading...", config.COL_TEXT_DIM,
                      config.SCREEN_W // 2, 150, anchor="center")
            return
        if not data.ok:
            draw_text(surf, self.fonts.reg, "No data for this city",
                      config.COL_TEXT_DIM, config.SCREEN_W // 2, 150,
                      anchor="center")
            return

        aqi_value, dom = aqi.overall_aqi(data.values)
        # temp banner + AQI
        if data.temperature is not None:
            rect = pygame.Rect(14, 46, 116, 52)
            rounded_rect(surf, config.COL_BG_CARD, rect, radius=10)
            draw_text(surf, self.fonts.big, f"{data.temperature:.0f}C",
                      config.COL_TEXT, 26, 56)
        aqi_badge(surf, self.fonts, aqi_value, 138, 46, 88, 52)

        x0, y0 = 14, 104
        cw, ch = 104, 52
        gx, gy = 8, 5
        i = 0
        for p in config.PARAM_ORDER:
            if p not in data.values:
                continue
            col = i % 2
            row = i // 2
            x = x0 + col * (cw + gx)
            y = y0 + row * (ch + gy)
            pollutant_card(surf, self.fonts, p, data.values.get(p),
                           data.contributors.get(p), x, y, cw, ch)
            i += 1

    def handle_tap(self, pos):
        if self.mode == "detail":
            self.mode = "list"
            return True
        for rect, idx in self._list_rects:
            if rect.collidepoint(pos):
                name, lat, lon = config.PRESET_CITIES[idx]
                self.selected = name
                self.mode = "detail"
                self.app.data.request_search(name, lat, lon)
                return True
        return False

    def scroll_by(self, delta):
        max_scroll = max(0, len(config.PRESET_CITIES) - self.rows_visible)
        self.scroll = max(0, min(max_scroll, self.scroll + delta))
