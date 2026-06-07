# -*- coding: utf-8 -*-
"""
OpenAQ v3 API client.

Responsibilities:
  * find the monitoring stations near a coordinate,
  * read each station's latest measurements,
  * AVERAGE each pollutant across all stations that report it
    (sensors missing a value are simply skipped),
  * return a clean dict the UI can display.

Network failures never raise to the caller: methods return None / empty
results and log to stderr, so the UI can keep showing the last good data.
"""

import sys
import time

import requests

import config


class AirData:
    """Result of one fetch: averaged pollutant values + metadata."""

    def __init__(self, location_name):
        self.location_name = location_name
        self.values = {}          # {param: averaged concentration}
        self.contributors = {}    # {param: how many stations contributed}
        self.station_count = 0    # how many stations were merged
        self.updated_ts = None    # epoch seconds of the freshest reading
        self.ok = False           # True if at least one value was obtained
        # Weather (from Open-Meteo); None if unavailable.
        self.temperature = None   # deg C
        self.humidity = None      # %
        self.wind = None          # km/h

    def __repr__(self):
        return (f"<AirData {self.location_name} ok={self.ok} "
                f"stations={self.station_count} values={self.values}>")


class OpenAQClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or config.OPENAQ_API_KEY
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": self.api_key,
            "User-Agent": "RSM-AirQualityStation/1.0 (student project)",
        })

    # -- low level -------------------------------------------------------
    def _get(self, path, params=None):
        url = f"{config.OPENAQ_BASE_URL}{path}"
        try:
            r = self.session.get(url, params=params, timeout=config.HTTP_TIMEOUT)
            if r.status_code == 401:
                print("[OpenAQ] 401 Unauthorized - check OPENAQ_API_KEY", file=sys.stderr)
                return None
            if r.status_code == 429:
                print("[OpenAQ] 429 Too Many Requests - slow down", file=sys.stderr)
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            print(f"[OpenAQ] request failed: {exc}", file=sys.stderr)
            return None

    # -- public ----------------------------------------------------------
    def find_stations(self, lat, lon, radius_m=None, limit=None):
        """Return a list of location dicts near (lat, lon)."""
        radius_m = radius_m or config.SEARCH_RADIUS_M
        limit = limit or config.MAX_STATIONS
        data = self._get("/locations", params={
            "coordinates": f"{lat},{lon}",
            "radius": radius_m,
            "limit": limit,
        })
        if not data:
            return []
        return data.get("results", [])

    def _latest_for_location(self, location_id):
        """Return the 'latest' results list for a location, or []."""
        data = self._get(f"/locations/{location_id}/latest")
        if not data:
            return []
        return data.get("results", [])

    def fetch_average(self, lat, lon, location_name):
        """
        Fetch all nearby stations and average each pollutant across the
        stations that report it. Missing values are skipped.
        """
        result = AirData(location_name)
        stations = self.find_stations(lat, lon)
        if not stations:
            return result

        # Build sensor_id -> parameter_name map from each station, and
        # accumulate sums/counts per parameter.
        sums = {}
        counts = {}
        now = time.time()
        used_stations = 0

        for station in stations[:config.MAX_STATIONS]:
            loc_id = station.get("id")
            # Map this station's sensor ids to parameter names.
            sensor_param = {}
            for s in station.get("sensors", []):
                p = (s.get("parameter") or {})
                name = p.get("name")
                if name in config.PARAM_LABELS:
                    sensor_param[s.get("id")] = name

            if not sensor_param:
                continue

            latest = self._latest_for_location(loc_id)
            if not latest:
                continue

            station_contributed = False
            for entry in latest:
                sid = entry.get("sensorsId") or entry.get("sensorId")
                param = sensor_param.get(sid)
                if not param:
                    continue
                value = entry.get("value")
                if value is None:
                    continue
                # Freshness check on the reading's timestamp if present.
                dt = (entry.get("datetime") or {})
                ts = _parse_ts(dt.get("utc"))
                if ts is not None and (now - ts) > config.STALE_AFTER:
                    continue
                sums[param] = sums.get(param, 0.0) + float(value)
                counts[param] = counts.get(param, 0) + 1
                station_contributed = True
                if ts is not None:
                    if result.updated_ts is None or ts > result.updated_ts:
                        result.updated_ts = ts

            if station_contributed:
                used_stations += 1

        # Compute averages.
        for param, total in sums.items():
            n = counts[param]
            if n > 0:
                result.values[param] = total / n
                result.contributors[param] = n

        result.station_count = used_stations
        result.ok = len(result.values) > 0
        if result.updated_ts is None and result.ok:
            result.updated_ts = now

        # Debug: show what was averaged (helps confirm NO2/SO2 etc. are live).
        summary = ", ".join(
            f"{p}={result.values[p]:.1f}(x{result.contributors[p]})"
            for p in result.values
        )
        print(f"[OpenAQ] {result.location_name}: {summary}")

        # Fetch weather (temperature/humidity/wind) from Open-Meteo.
        if config.ENABLE_TEMPERATURE:
            self._fetch_weather(lat, lon, result)
        return result

    def _fetch_weather(self, lat, lon, result):
        """Populate result.temperature/humidity/wind from Open-Meteo."""
        try:
            # Use a plain request (NOT the OpenAQ session) so the X-API-Key
            # header and base settings don't interfere with Open-Meteo.
            r = requests.get(
                config.OPENMETEO_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
                },
                timeout=config.HTTP_TIMEOUT,
                headers={"User-Agent": "RSM-AirQualityStation/1.0"},
            )
            r.raise_for_status()
            cur = (r.json() or {}).get("current", {})
            result.temperature = cur.get("temperature_2m")
            result.humidity = cur.get("relative_humidity_2m")
            result.wind = cur.get("wind_speed_10m")
            print(f"[OpenMeteo] {result.location_name}: "
                  f"t={result.temperature} h={result.humidity} w={result.wind}")
        except Exception as exc:
            print(f"[OpenMeteo] weather fetch failed: {exc}", file=sys.stderr)


def _parse_ts(iso_str):
    """Parse an ISO8601 UTC timestamp to epoch seconds; None on failure."""
    if not iso_str:
        return None
    try:
        from datetime import datetime, timezone
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None
