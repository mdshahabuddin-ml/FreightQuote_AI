import os
import requests
import pandas as pd
import streamlit as st

from datetime import datetime


VISUAL_CROSSING_URL = (
    "https://weather.visualcrossing.com/"
    "VisualCrossingWebServices/rest/services/timeline"
)

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"


def get_weather_api_key():
    """Read the key without exposing it."""
    key = os.environ.get("VISUAL_CROSSING_API_KEY", "").strip()

    if not key:
        try:
            from google.colab import userdata
            key = userdata.get("VISUAL_CROSSING_API_KEY") or ""
        except Exception:
            pass

    if not key:
        try:
            key = st.secrets.get("VISUAL_CROSSING_API_KEY", "")
        except Exception:
            pass

    if not key:
        raise RuntimeError(
            "VISUAL_CROSSING_API_KEY is missing. "
            "Add it to Colab Secrets and enable notebook access."
        )

    return key


@st.cache_data(ttl=900, show_spinner=False)
def fetch_weather(latitude, longitude):
    """Fetch actual weather forecast data for one location."""
    key = get_weather_api_key()
    location = f"{latitude},{longitude}"

    response = requests.get(
        f"{VISUAL_CROSSING_URL}/{location}",
        params={
            "key": key,
            "unitGroup": "metric",
            "include": "current,hours,days,alerts",
            "contentType": "json",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=900, show_spinner=False)
def fetch_marine(latitude, longitude):
    """Fetch marine forecast; values may be unavailable near some coasts."""
    response = requests.get(
        MARINE_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": (
                "wave_height,wave_direction,wave_period,"
                "wind_wave_height,swell_wave_height"
            ),
            "hourly": "wave_height",
            "forecast_days": 2,
            "timezone": "auto",
            "cell_selection": "sea",
        },
        timeout=25,
    )
    response.raise_for_status()
    return response.json()


def assess_weather_risk(current, marine_current):
    """Indicative screening rules, not official safety thresholds."""
    gust = current.get("windgust")
    wind = current.get("windspeed")
    rain_probability = current.get("precipprob")
    wave = marine_current.get("wave_height")

    reasons = []
    score = 0

    # Thresholds are configurable example values.
    if gust is not None and gust >= 70:
        score += 2
        reasons.append("Strong wind gusts reported in current conditions.")
    elif gust is not None and gust >= 50:
        score += 1
        reasons.append("Elevated wind gusts.")

    if wave is not None and wave >= 4:
        score += 2
        reasons.append("High forecast wave height.")
    elif wave is not None and wave >= 2.5:
        score += 1
        reasons.append("Elevated forecast wave height.")

    if rain_probability is not None and rain_probability >= 70:
        score += 1
        reasons.append("High precipitation probability.")

    if score >= 3:
        level = "High"
    elif score >= 1:
        level = "Moderate"
    else:
        level = "Low"

    # Do not call conditions low-risk if key data is missing.
    if gust is None and wind is None and wave is None:
        level = "Insufficient data"
        reasons = ["Wind and marine data are unavailable."]
    elif wave is None:
        reasons.append(
            "Wave data unavailable; marine risk assessment is incomplete."
        )

    return level, reasons


def render_weather_risk_page(*args, **kwargs):
    st.subheader("Weather Risk")
    st.caption(
        "Shipment weather exposure · Forecasts · Marine conditions"
    )

    st.info(
        "Select a vessel's latest AIS position or enter coordinates "
        "for a shipment route point."
    )

    use_ais = st.checkbox(
        "Use coordinates from the Open Waters vessel cache"
    )

    selected_vessel = None
    latitude = None
    longitude = None

    if use_ais:
        try:
            from aisstream_carriers import _get_stream

            rows = _get_stream().get_rows()

            if rows:
                options = {
                    f"{r['vessel']} — MMSI {r['mmsi']}": r
                    for r in rows
                }
                label = st.selectbox("Vessel", list(options.keys()))
                selected_vessel = options[label]
                latitude = float(selected_vessel["latitude"])
                longitude = float(selected_vessel["longitude"])
            else:
                st.warning("No vessel positions are cached yet.")
        except Exception as exc:
            st.warning(
                f"Vessel cache unavailable: {type(exc).__name__}. "
                "You can enter coordinates manually."
            )

    if latitude is None or longitude is None:
        c1, c2 = st.columns(2)

        with c1:
            latitude = st.number_input(
                "Latitude",
                min_value=-90.0,
                max_value=90.0,
                value=1.425753,
                format="%.6f",
            )

        with c2:
            longitude = st.number_input(
                "Longitude",
                min_value=-180.0,
                max_value=180.0,
                value=103.896562,
                format="%.6f",
            )

    if st.button("Refresh Weather Risk", type="primary"):
        fetch_weather.clear()
        fetch_marine.clear()

    try:
        with st.spinner("Loading weather and marine forecasts..."):
            data = fetch_weather(latitude, longitude)
            marine_data = fetch_marine(latitude, longitude)

    except requests.HTTPError as exc:
        st.error(
            "Weather API request failed. Check the API key, "
            "account quota, and provider response."
        )
        if exc.response is not None:
            st.caption(
                f"HTTP {exc.response.status_code}: "
                f"{exc.response.text[:300]}"
            )
        return

    except requests.RequestException as exc:
        st.error(f"Could not reach a weather provider: {exc}")
        return

    except RuntimeError as exc:
        st.error(str(exc))
        return

    current = data.get("currentConditions") or {}
    marine_current = marine_data.get("current") or {}
    level, reasons = assess_weather_risk(current, marine_current)

    st.markdown("### Shipment location")

    if selected_vessel:
        st.write(
            f"Vessel: {selected_vessel['vessel']} "
            f"· MMSI {selected_vessel['mmsi']}"
        )

    st.write(f"Coordinates: {latitude:.6f}, {longitude:.6f}")

    st.map(pd.DataFrame([{
        "latitude": latitude,
        "longitude": longitude,
    }]))

    st.markdown("### Current weather")

    cols = st.columns(4)
    cols[0].metric("Temperature", f"{current.get('temp', 'N/A')} °C")
    cols[1].metric("Wind", f"{current.get('windspeed', 'N/A')} km/h")
    cols[2].metric("Wind gust", f"{current.get('windgust', 'N/A')} km/h")
    cols[3].metric("Rain probability", f"{current.get('precipprob', 'N/A')} %")

    st.markdown("### Marine conditions")

    mcols = st.columns(4)
    mcols[0].metric("Wave height", f"{marine_current.get('wave_height', 'N/A')} m")
    mcols[1].metric("Swell height", f"{marine_current.get('swell_wave_height', 'N/A')} m")
    mcols[2].metric("Wave period", f"{marine_current.get('wave_period', 'N/A')} s")
    mcols[3].metric("Wave direction", f"{marine_current.get('wave_direction', 'N/A')}°")

    st.markdown("### Indicative risk assessment")

    if level == "High":
        st.error("High indicative weather risk")
    elif level == "Moderate":
        st.warning("Moderate indicative weather risk")
    elif level == "Low":
        st.success("Low according to available screening rules")
    else:
        st.info("Insufficient data")

    for reason in reasons:
        st.write(f"- {reason}")

    st.caption(
        "These are illustrative project thresholds, not official "
        "navigation warnings. Missing data must not be interpreted as safe."
    )

    st.markdown("### Daily forecast")

    days = data.get("days") or []
    if days:
        columns = [
            "datetime", "tempmin", "tempmax", "precipprob",
            "windspeed", "windgust", "conditions"
        ]
        forecast_df = pd.DataFrame(days)
        available = [c for c in columns if c in forecast_df.columns]
        st.dataframe(
            forecast_df[available],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No daily forecast was returned.")

    alerts = data.get("alerts") or []
    st.markdown("### Weather alerts")
    if alerts:
        for alert in alerts:
            st.warning(
                f"{alert.get('event', 'Weather alert')}: "
                f"{alert.get('headline', alert.get('description', 'See source'))}"
            )
    else:
        st.write("No alerts were returned for this location.")

    st.caption(
        f"Data retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
        "Weather: Visual Crossing. Marine forecast: Open-Meteo. "
        "Forecast data is model-based and can be incomplete."
    )
    st.markdown(
        "[Visual Crossing API](https://www.visualcrossing.com/resources/documentation/weather-api/timeline-weather-api/) · "
        "[Open-Meteo Marine API](https://open-meteo.com/en/docs/marine-weather-api)"
    )
