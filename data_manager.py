# -*- coding: utf-8 -*-
"""
Background data manager.

Runs the (slow, network-bound) OpenAQ fetches on a worker thread so the
Pygame UI stays at a smooth frame rate. The UI reads cached AirData via
thread-safe getters.

  * Craiova data refreshes automatically every REFRESH_INTERVAL seconds.
  * A "search" location can be requested on demand from Screen 3; its
    result is fetched once and cached until another search is requested.
"""

import threading
import time

import config
from api_client import OpenAQClient, AirData


class DataManager:
    def __init__(self):
        self.client = OpenAQClient()
        self._lock = threading.Lock()

        self._craiova = AirData(config.CRAIOVA_NAME)
        self._craiova_last = 0

        self._search = None            # AirData for the searched city
        self._search_request = None    # (name, lat, lon) pending
        self._search_busy = False

        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop = True

    # -- getters (thread-safe) ------------------------------------------
    def get_craiova(self):
        with self._lock:
            return self._craiova

    def get_search(self):
        with self._lock:
            return self._search

    def is_search_busy(self):
        with self._lock:
            return self._search_busy

    # -- request a search ------------------------------------------------
    def request_search(self, name, lat, lon):
        with self._lock:
            self._search_request = (name, lat, lon)
            self._search_busy = True

    # -- worker ----------------------------------------------------------
    def _run(self):
        # Initial Craiova fetch immediately on startup.
        self._refresh_craiova()
        while not self._stop:
            now = time.time()
            # Periodic Craiova refresh.
            if now - self._craiova_last >= config.REFRESH_INTERVAL:
                self._refresh_craiova()
            # Pending search?
            req = None
            with self._lock:
                if self._search_request is not None:
                    req = self._search_request
                    self._search_request = None
            if req is not None:
                name, lat, lon = req
                data = self.client.fetch_average(lat, lon, name)
                with self._lock:
                    self._search = data
                    self._search_busy = False
            time.sleep(0.5)

    def _refresh_craiova(self):
        data = self.client.fetch_average(
            config.CRAIOVA_LAT, config.CRAIOVA_LON, config.CRAIOVA_NAME)
        with self._lock:
            # Keep previous good data if this fetch failed entirely.
            if data.ok or not self._craiova.ok:
                self._craiova = data
            self._craiova_last = time.time()
