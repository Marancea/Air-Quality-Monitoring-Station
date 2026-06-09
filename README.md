# Air Quality Monitoring Station

A 3-screen touchscreen application for the Raspberry Pi Zero WH + AZ-Touch Pi0
(2.8" ILI9341 display, 320x240). It reads air quality data from the OpenAQ v3
API and shows it on three swipeable screens, like flipping pages on a phone.

## The three screens

1. **Craiova** (always): all available pollutants for Craiova, with PM2.5 and
   PM10 as the visual highlight, plus the overall AQI and the gases. The values
   are the **average across all OpenAQ stations in Craiova**; sensors that are
   missing a value are simply skipped.
2. **Local vs OpenAQ**: your own SDS011 sensor reading (received over MQTT from
   the ESP32 node) shown side by side with the OpenAQ city average, plus the
   difference. Shows "Waiting for sensor..." until the node publishes.
3. **Search**: pick another city from a list and view its data from the API.

## Navigation

- **Tap the arrows** in the bottom bar to move between the three screens; the
  dots show which screen you are on.
- On **Search**, tap a city to open it; tap anywhere to go back. Drag up/down
  to scroll the city list.
- Keyboard (when testing on a PC): Left/Right arrows change screen, Esc quits.

## Setup

1. Put your OpenAQ API key in `config.py`:
   ```python
   OPENAQ_API_KEY = "your-key-here"
   ```
   Get a free key at https://explore.openaq.org (v3 requires one).

2. Install dependencies:
   ```bash
   pip3 install -r requirements.txt --break-system-packages
   ```

3. Run:
   ```bash
   python3 main.py              # on the Pi: uses the TFT framebuffer + touch
   python3 main.py --windowed   # on a PC: opens a 320x240 window for testing
   ```

The app auto-detects the Raspberry Pi and uses the TFT framebuffer
(`/dev/fb1`); on any other machine it opens a normal window so you can develop
without the hardware.

## MQTT (Screen 2)

The ESP32 + SDS011 node should publish a JSON message to the topic
`weather/sds011` on the broker running on the Pi, for example:

```json
{"pm25": 12.3, "pm10": 18.7, "sensor": "sds011", "rssi": -62}
```

Adjust `MQTT_HOST`, `MQTT_PORT`, and `MQTT_TOPIC` in `config.py` if needed.
If `paho-mqtt` is not installed, Screen 2 still loads and shows a notice.

## Files

| File              | Responsibility                                        |
|-------------------|-------------------------------------------------------|
| `config.py`       | All settings: API key, location, colors, layout       |
| `api_client.py`   | OpenAQ v3 client + multi-station averaging            |
| `aqi.py`          | US EPA Air Quality Index calculation                  |
| `mqtt_client.py`  | Background MQTT client for the local SDS011 node      |
| `data_manager.py` | Background thread that refreshes data without blocking |
| `screens.py`      | The three screens + drawing helpers                   |
| `main.py`         | Display setup, swipe navigation, main loop            |

## Run as a service (auto-start on boot)

Create `/etc/systemd/system/weather-station.service`:

```ini
[Unit]
Description=Air quality monitoring station
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/weather_station/main.py
WorkingDirectory=/home/pi/weather_station
Restart=on-failure
RestartSec=10
User=pi
Environment=SDL_FBDEV=/dev/fb1

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl enable weather-station
sudo systemctl start weather-station
```

## Configuration before running

Two settings must be filled in with your own values (they ship as placeholders
so no secrets are committed to the repository):

1. `config.py` -> `OPENAQ_API_KEY` : your free OpenAQ v3 API key
   (get one at https://explore.openaq.org).
2. `esp32_sds011/esp32_sds011.ino` -> `WIFI_SSID`, `WIFI_PASSWORD`, and
   `MQTT_HOST_IP` : your network name/password and the Raspberry Pi's IP
   (used as a fallback; the sketch normally finds the Pi by hostname via mDNS).

## License

Released under the MIT License - see the LICENSE file.
