# -*- coding: utf-8 -*-
"""
Global configuration for the air quality monitoring station.

All tunable values live here so the rest of the code stays clean.
Edit OPENAQ_API_KEY and the MQTT settings to match your setup.
"""

# ---------------------------------------------------------------------------
# OpenAQ API
# ---------------------------------------------------------------------------
# OpenAQ v3 REQUIRES an API key, sent in the "X-API-Key" header.
# Get yours (free) at https://explore.openaq.org -> account settings.
OPENAQ_API_KEY = "PUT-YOUR-OPENAQ-API-KEY-HERE"

OPENAQ_BASE_URL = "https://api.openaq.org/v3"

# Default location shown on Screen 1 (always Craiova).
CRAIOVA_LAT = 44.3302
CRAIOVA_LON = 23.7949
CRAIOVA_NAME = "Craiova"

# Radius (meters) used when searching for stations around a coordinate.
SEARCH_RADIUS_M = 25000          # 25 km – captures all Craiova stations
MAX_STATIONS = 10                # safety cap on how many stations we merge

# How often to refresh data from the API (seconds).
REFRESH_INTERVAL = 300           # 5 minutes – polite to the API

# Open-Meteo (free, no key) – used for temperature/humidity/wind, which
# OpenAQ usually does not provide.
OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"
ENABLE_TEMPERATURE = True

# Measurements older than this (seconds) are treated as stale and ignored.
STALE_AFTER = 6 * 3600           # 6 hours

# HTTP timeout for each request (seconds).
HTTP_TIMEOUT = 10

# ---------------------------------------------------------------------------
# MQTT (local SDS011 sensor node, for Screen 2)
# ---------------------------------------------------------------------------
MQTT_HOST = "127.0.0.1"          # broker runs on the Pi itself
MQTT_PORT = 1883
MQTT_TOPIC = "weather/sds011"
MQTT_KEEPALIVE = 60
# Local reading is considered "fresh" only if newer than this (seconds).
SENSOR_STALE_AFTER = 120

# ---------------------------------------------------------------------------
# Touch calibration (XPT2046 raw ADC ranges -> screen pixels).
# If taps land in the wrong place, adjust these. SWAP/INVERT handle the
# screen rotation. Good starting values for AZ-Touch Pi0 in portrait.
# ---------------------------------------------------------------------------
TOUCH_MIN_X = 230
TOUCH_MAX_X = 3800
TOUCH_MIN_Y = 285
TOUCH_MAX_Y = 3870
TOUCH_SWAP_XY = False
TOUCH_INVERT_X = True
TOUCH_INVERT_Y = False

# ---------------------------------------------------------------------------
# Display  (PORTRAIT: the framebuffer is rotated 90 deg at the driver level,
# so it is 240 wide x 320 tall)
# ---------------------------------------------------------------------------
SCREEN_W = 240
SCREEN_H = 320
FPS = 30

# Preset cities for the Screen 3 search list (name -> (lat, lon)).
# Keeps text entry off a tiny resistive screen; users pick from the list.
PRESET_CITIES = [
    ("Craiova",        44.3302, 23.7949),
    ("Bucuresti",      44.4268, 26.1025),
    ("Cluj-Napoca",    46.7712, 23.6236),
    ("Timisoara",      45.7489, 21.2087),
    ("Iasi",           47.1585, 27.6014),
    ("Constanta",      44.1598, 28.6348),
    ("Brasov",         45.6579, 25.6012),
    ("Sibiu",          45.7983, 24.1256),
    ("Ploiesti",       44.9469, 26.0299),
    ("Oradea",         47.0465, 21.9189),
]

# ---------------------------------------------------------------------------
# Parameters we care about (OpenAQ parameter "name" -> friendly label + unit).
# OpenAQ already returns physical units; we keep them as-is.
# ---------------------------------------------------------------------------
PARAM_LABELS = {
    "pm25": ("PM2.5", "ug/m3"),
    "pm10": ("PM10",  "ug/m3"),
    "no2":  ("NO2",   "ug/m3"),
    "o3":   ("O3",    "ug/m3"),
    "so2":  ("SO2",   "ug/m3"),
    "co":   ("CO",    "ug/m3"),
}

# Display order (particulates first – they are the Screen 1 highlight).
PARAM_ORDER = ["pm25", "pm10", "no2", "o3", "so2", "co"]

# ---------------------------------------------------------------------------
# Colors (RGB).  Dark dashboard theme with AQI-driven accents.
# ---------------------------------------------------------------------------
COL_BG          = (18, 22, 33)       # near-black blue
COL_BG_CARD     = (28, 34, 49)       # slightly lighter card
COL_BG_CARD_HI  = (36, 44, 64)
COL_TEXT        = (232, 236, 245)
COL_TEXT_DIM    = (140, 150, 170)
COL_TEXT_FAINT  = (90, 100, 120)
COL_ACCENT      = (64, 156, 255)     # blue accent for chrome
COL_DIVIDER     = (48, 56, 78)
COL_WARN        = (255, 170, 60)
COL_GOOD        = (0, 200, 120)
COL_BAD         = (220, 60, 80)

# AQI category colors (US EPA palette), index 0..5.
AQI_COLORS = [
    (0, 200, 120),    # Good
    (240, 210, 60),   # Moderate
    (255, 150, 50),   # Unhealthy for sensitive groups
    (220, 60, 80),    # Unhealthy
    (150, 60, 170),   # Very unhealthy
    (120, 30, 50),    # Hazardous
]
AQI_LABELS = [
    "Good",
    "Moderate",
    "Sensitive",
    "Unhealthy",
    "Very bad",
    "Hazardous",
]
