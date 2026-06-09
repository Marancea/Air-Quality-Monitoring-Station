# -*- coding: utf-8 -*-
"""
Air Quality Index (AQI) calculation following the US EPA method.

The EPA AQI is a piecewise-linear function of pollutant concentration.
For each pollutant we look up the breakpoint interval the concentration
falls into, then linearly interpolate to get a 0..500 sub-index.
The overall AQI is the MAX of the available sub-indices, and the
"dominant pollutant" is the one that produced that maximum.

Reference: EPA 454/B-18-007, "Technical Assistance Document for the
Reporting of Daily Air Quality - the Air Quality Index (AQI)".
"""

# Breakpoints per pollutant: list of (C_low, C_high, I_low, I_high).
# Concentrations in ug/m3 (PM) or the EPA's stated units; for a didactic
# station we apply the PM tables directly and approximate gases in ug/m3.
_BREAKPOINTS = {
    "pm25": [
        (0.0, 12.0, 0, 50),
        (12.1, 35.4, 51, 100),
        (35.5, 55.4, 101, 150),
        (55.5, 150.4, 151, 200),
        (150.5, 250.4, 201, 300),
        (250.5, 350.4, 301, 400),
        (350.5, 500.4, 401, 500),
    ],
    "pm10": [
        (0, 54, 0, 50),
        (55, 154, 51, 100),
        (155, 254, 101, 150),
        (255, 354, 151, 200),
        (355, 424, 201, 300),
        (425, 504, 301, 400),
        (505, 604, 401, 500),
    ],
    # Gaseous pollutants: simplified ug/m3 breakpoints suitable for a
    # demonstrative station (not the official ppb tables, but monotonic
    # and category-consistent).
    "no2": [
        (0, 40, 0, 50),
        (41, 90, 51, 100),
        (91, 120, 101, 150),
        (121, 230, 151, 200),
        (231, 340, 201, 300),
        (341, 1000, 301, 500),
    ],
    "o3": [
        (0, 60, 0, 50),
        (61, 100, 51, 100),
        (101, 140, 101, 150),
        (141, 180, 151, 200),
        (181, 240, 201, 300),
        (241, 600, 301, 500),
    ],
    "so2": [
        (0, 20, 0, 50),
        (21, 80, 51, 100),
        (81, 250, 101, 150),
        (251, 350, 151, 200),
        (351, 500, 201, 300),
        (501, 1250, 301, 500),
    ],
    "co": [
        # CO often reported in mg/m3; if values look like ug/m3 (large),
        # the interpolation still saturates gracefully.
        (0, 4400, 0, 50),
        (4401, 9400, 51, 100),
        (9401, 12400, 101, 150),
        (12401, 15400, 151, 200),
        (15401, 30400, 201, 300),
        (30401, 60400, 301, 500),
    ],
}


def sub_index(parameter, concentration):
    """Return the integer AQI sub-index for one pollutant, or None."""
    if concentration is None:
        return None
    table = _BREAKPOINTS.get(parameter)
    if not table:
        return None
    c = float(concentration)
    if c < 0:
        return None
    for c_low, c_high, i_low, i_high in table:
        if c_low <= c <= c_high:
            # linear interpolation
            return round((i_high - i_low) / (c_high - c_low) * (c - c_low) + i_low)
    # Above the last breakpoint -> clamp to the top of the scale.
    return table[-1][3]


def aqi_category(aqi):
    """Map a 0..500 AQI value to a category index 0..5."""
    if aqi is None:
        return None
    if aqi <= 50:
        return 0
    if aqi <= 100:
        return 1
    if aqi <= 150:
        return 2
    if aqi <= 200:
        return 3
    if aqi <= 300:
        return 4
    return 5


def overall_aqi(concentrations):
    """
    Given a dict {parameter: concentration}, return (aqi, dominant_param).

    aqi is the maximum sub-index across all available pollutants.
    Returns (None, None) if nothing could be computed.
    """
    best_aqi = None
    best_param = None
    for param, conc in concentrations.items():
        si = sub_index(param, conc)
        if si is None:
            continue
        if best_aqi is None or si > best_aqi:
            best_aqi = si
            best_param = param
    return best_aqi, best_param
