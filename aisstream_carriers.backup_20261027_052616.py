
import asyncio
import html
import json
import os
import threading
from datetime import datetime, timezone

import folium
import pandas as pd
import streamlit as st
import websockets
from streamlit_autorefresh import st_autorefresh
from streamlit_folium import st_folium

AIS_URL = "wss://stream.aisstream.io/v0/stream"
MAX_VESSELS = 1500

REGIONS = {
    "Singapore Strait": {
        "bbox": [[1.0, 103.4], [1.5, 104.2]],
        "center": [1.25, 103.8], "zoom": 8,
    },
    "English Channel": {
        "bbox": [[49.5, -5.5], [51.5, 2.5]],
        "center": [50.5, -1.5], "zoom": 6,
    },
    "Suez Canal": {
        "bbox": [[29.5, 32.0], [31.5, 34.0]],
        "center": [30.5, 33.0], "zoom": 7,
    },
    "Mumbai approaches": {
        "bbox": [[18.0, 71.0], [20.5, 73.5]],
        "center": [19.0, 72.2], "zoom": 7,
    },
}


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class VesselStream:
    """Background AIS consumer. It never calls Streamlit APIs."""

    def __init__(self):
        self.lock = threading.RLock()
        self.rows = {}
        self.status = "Not connected"
        self.last_error = None
        self.last_received = None
        self.thread = None
        self.stop_event = None
        self.config = None

    def snapshot(self):
        with self.lock:
            rows = [dict(v) for v in self.rows.values()]
            return rows, self.status, self.last_error, self.last_received

    def start(self, key, region_name, bbox):
        config = (key, region_name, json.dumps(bbox))
        if self.thread and self.thread.is_alive() and self.config == config:
            return

        self.stop()
        event = threading.Event()
        self.stop_event = event
        self.config = config

        with self.lock:
            self.rows.clear()
            self.status = "Connecting"
            self.last_error = None
            self.last_received = None

        self.thread = threading.Thread(
            target=self._thread_main,
            args=(key, region_name, bbox, event),
            daemon=True,
            name="AISStreamConsumer",
        )
        self.thread.start()

    def stop(self):
        if self.stop_event:
            self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.thread = None
        self.stop_event = None
        self.config = None

    def _thread_main(self, key, region, bbox, stop_event):
        try:
            asyncio.run(self._consume(key, region, bbox, stop_event))
        except Exception as exc:
            with self.lock:
                self.status = "Stream stopped"
                self.last_error = type(exc).__name__

    async def _consume(self, key, region, bbox, stop_event):
        delay = 1

        while not stop_event.is_set():
            try:
                with self.lock:
                    self.status = "Connecting"
                    self.last_error = None

                async with websockets.connect(
                    AIS_URL,
                    compression="deflate",
                    ping_interval=20,
                    ping_timeout=20,
                    open_timeout=12,
                    max_size=2**20,
                ) as ws:
                    # AISStream requires the complete subscription promptly.
                    await ws.send(json.dumps({
                        "APIKey": key,
                        "BoundingBoxes": [bbox],
                        "FilterMessageTypes": [
                            "PositionReport",
                            "StandardClassBPositionReport",
                            "ExtendedClassBPositionReport",
                        ],
                    }))

                    with self.lock:
                        self.status = f"Subscribed to {region}; waiting for AIS"

                    delay = 1

                    while not stop_event.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1)
                        except asyncio.TimeoutError:
                            continue

                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="replace")

                        try:
                            event = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            continue

                        kind = event.get("MessageType", "")

                        if kind == "SubscriptionConfirmation":
                            with self.lock:
                                self.status = f"Subscription accepted: {region}"
                            continue

                        if kind.lower() == "error":
                            with self.lock:
                                self.status = "AISStream returned an error"
                                self.last_error = "Provider error response"
                            continue

                        if kind in (
                            "PositionReport",
                            "StandardClassBPositionReport",
                            "ExtendedClassBPositionReport",
                        ):
                            self._save_position(event, kind)

            except Exception as exc:
                with self.lock:
                    self.status = "Disconnected; retrying"
                    self.last_error = type(exc).__name__

            # Exponential reconnect backoff; do not print credentials.
            for _ in range(delay * 10):
                if stop_event.is_set():
                    break
                await asyncio.sleep(0.1)
            delay = min(delay * 2, 30)

        with self.lock:
            self.status = "Stopped"

    def _save_position(self, event, kind):
        meta = event.get("MetaData") or {}
        payload = (event.get("Message") or {}).get(kind) or {}

        mmsi = meta.get("MMSI") or payload.get("UserID")
        lat = meta.get("Latitude", meta.get("latitude", payload.get("Latitude")))
        lon = meta.get("Longitude", meta.get("longitude", payload.get("Longitude")))

        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            return

        if mmsi is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return

        received = _utc_now()
        row = {
            "MMSI": str(mmsi),
            "Vessel": str(meta.get("ShipName") or "Unknown vessel").strip(),
            "Latitude": lat,
            "Longitude": lon,
            "Speed (knots)": payload.get("Sog"),
            "Course (°)": payload.get("Cog"),
            "Heading (°)": payload.get("TrueHeading"),
            "Received UTC": received,
        }

        with self.lock:
            self.rows[str(mmsi)] = row
            while len(self.rows) > MAX_VESSELS:
                self.rows.pop(next(iter(self.rows)))
            self.last_received = received
            self.status = "Receiving live AIS positions"


@st.cache_resource
def _get_stream():
    return VesselStream()


def render_carriers_page():
    # This function is called by fq_ui.render_app(), not directly in a notebook.
    st_autorefresh(interval=5000, key="ais_carriers_refresh")

    st.title("Carriers")
    st.caption(
        "Live vessel positions from AISStream. "
        "Only real messages received from the provider are displayed."
    )

    key = os.environ.get("AISSTREAM_API_KEY", "").strip()
    if not key:
        st.error(
            "AISStream key is not available to this Streamlit process. "
            "Load AISSTREAM_API_KEY from Colab Secrets before starting Streamlit."
        )
        return

    region_name = st.selectbox(
        "Tracking region", list(REGIONS.keys()), key="ais_carriers_region"
    )
    region = REGIONS[region_name]

    stream = _get_stream()
    stream.start(key, region_name, region["bbox"])
    vessels, status, error, last_received = stream.snapshot()

    a, b, c = st.columns(3)
    a.metric("Vessels received", len(vessels))
    b.metric("Region", region_name)
    c.metric("Stream", "Receiving" if last_received else "Waiting")

    st.caption("Connection: " + status)
    if error:
        st.warning("Latest connection issue: " + error)

    if not vessels:
        st.info(
            "No live position reports have arrived yet for this region. "
            "Wait for AIS messages or choose another region. "
            "No sample vessels or synthetic positions are added."
        )

    m = folium.Map(
        location=region["center"],
        zoom_start=region["zoom"],
        tiles="OpenStreetMap",
        control_scale=True,
    )

    for v in vessels:
        safe_name = html.escape(v["Vessel"])
        popup = (
            f"<b>{safe_name}</b><br>MMSI: {html.escape(v['MMSI'])}<br>"
            f"Speed: {html.escape(str(v['Speed (knots)']))} knots<br>"
            f"Course: {html.escape(str(v['Course (°)']))}°<br>"
            f"Received UTC: {html.escape(v['Received UTC'])}"
        )
        folium.CircleMarker(
            [v["Latitude"], v["Longitude"]],
            radius=5,
            color="#0e7490",
            fill=True,
            fill_opacity=0.85,
            tooltip=f"{v['Vessel']} · MMSI {v['MMSI']}",
            popup=folium.Popup(popup, max_width=300),
        ).add_to(m)

    st.subheader("Live vessel map")
    st_folium(
        m,
        width=1100,
        height=470,
        returned_objects=[],
        key="ais_carriers_map",
    )

    st.subheader("Received vessel positions")
    if vessels:
        df = pd.DataFrame(vessels).sort_values("Received UTC", ascending=False)
        st.dataframe(df, width="stretch", hide_index=True)
        st.caption("Last report received (UTC): " + str(last_received))
    else:
        st.write("The table will populate when real AIS position messages arrive.")

    st.caption(
        "Source: AISStream. The latest-position cache is held in memory only. "
        "This page does not write to or migrate your SQLite database."
    )
