# -*- coding: utf-8 -*-
"""
MQTT client for the local SDS011 sensor node (Screen 2).

The ESP32 publishes a JSON message every ~30 s on topic weather/sds011,
e.g. {"pm25": 12.3, "pm10": 18.7, "sensor": "sds011", "rssi": -62}.

This client runs the paho-mqtt network loop in a background thread and
keeps the most recent reading in memory. The UI polls .get_reading().

If paho-mqtt is not installed (e.g. when testing on a PC), the client
degrades gracefully: it simply never reports a reading.
"""

import json
import sys
import threading
import time

import config

try:
    import paho.mqtt.client as mqtt
    _HAS_MQTT = True
except Exception:
    _HAS_MQTT = False


class SensorReading:
    def __init__(self, pm25=None, pm10=None, rssi=None, ts=None):
        self.pm25 = pm25
        self.pm10 = pm10
        self.rssi = rssi
        self.ts = ts or time.time()

    def is_fresh(self):
        return (time.time() - self.ts) <= config.SENSOR_STALE_AFTER


class MqttSensor:
    def __init__(self):
        self._lock = threading.Lock()
        self._reading = None
        self._connected = False
        self._client = None
        self._started = False

    # -- lifecycle -------------------------------------------------------
    def start(self):
        """Begin connecting in the background. Safe to call once."""
        if self._started:
            return
        self._started = True
        if not _HAS_MQTT:
            print("[MQTT] paho-mqtt not installed; Screen 2 will wait.",
                  file=sys.stderr)
            return
        try:
            # paho-mqtt 2.x signature; fall back to 1.x if needed.
            try:
                self._client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION1)
            except Exception:
                self._client = mqtt.Client()
            self._client.on_connect = self._on_connect
            self._client.on_message = self._on_message
            self._client.on_disconnect = self._on_disconnect
            self._client.connect_async(
                config.MQTT_HOST, config.MQTT_PORT, config.MQTT_KEEPALIVE)
            self._client.loop_start()
        except Exception as exc:
            print(f"[MQTT] could not start: {exc}", file=sys.stderr)

    def stop(self):
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass

    # -- callbacks -------------------------------------------------------
    def _on_connect(self, client, userdata, flags, rc, *args):
        if rc == 0:
            self._connected = True
            client.subscribe(config.MQTT_TOPIC)
            print(f"[MQTT] connected, subscribed to {config.MQTT_TOPIC}")
        else:
            print(f"[MQTT] connect failed rc={rc}", file=sys.stderr)

    def _on_disconnect(self, *args):
        self._connected = False

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return
        pm25 = _num(payload.get("pm25"))
        pm10 = _num(payload.get("pm10"))
        rssi = _num(payload.get("rssi"))
        with self._lock:
            self._reading = SensorReading(pm25=pm25, pm10=pm10, rssi=rssi)

    # -- access ----------------------------------------------------------
    def get_reading(self):
        """Return the latest SensorReading, or None if none/stale."""
        with self._lock:
            r = self._reading
        if r is None:
            return None
        return r

    @property
    def connected(self):
        return self._connected

    @property
    def available(self):
        return _HAS_MQTT


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
