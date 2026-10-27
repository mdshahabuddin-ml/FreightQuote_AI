import os
import json
import time
import threading
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import websocket


AIS_URL = "wss://ais.openwaters.io/v0/stream"

# Selected busy shipping corridors.
# Each box is [[latitude, longitude], [latitude, longitude]].
# These boxes are NOT a complete worldwide ocean feed.
SHIPPING_LANES = [
    [[49, -6], [52, 2]],       # English Channel
    [[35, -7], [37, -3]],      # Gibraltar
    [[28, 31], [32, 34]],      # Suez Canal area
    [[24, 54], [27, 58]],      # Strait of Hormuz
    [[17, 70], [21, 74]],      # Mumbai / Arabian Sea
    [[0, 102], [3, 106]],      # Singapore Strait
    [[20, 113], [24, 119]],    # Hong Kong / South China Sea
    [[28, 120], [32, 125]],    # Shanghai / East China Sea
    [[7, -80], [10, -77]],     # Panama Canal approaches
    [[50, 2], [53, 7]],        # Rotterdam / North Sea
    [[38, -75], [42, -70]],    # US East Coast
    [[-35, 17], [-32, 22]],    # Cape of Good Hope
]


def _get_api_key():
    key = os.environ.get("OPENWATERS_API_KEY", "").strip()

    if not key:
        try:
            key = st.secrets.get("OPENWATERS_API_KEY", "")
        except Exception:
            key = ""

    if not key:
        raise RuntimeError(
            "OPENWATERS_API_KEY is missing. "
            "Load it from Colab Secrets before starting Streamlit."
        )

    return key


class OpenWatersVesselStream:
    """Background AIS receiver with an in-memory vessel cache."""

    def __init__(self):
        self.vessels = {}
        self.lock = threading.Lock()
        self.thread = None
        self.status = "Waiting to connect"
        self.last_message = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return

        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="openwaters-ais-stream",
        )
        self.thread.start()

    def _run(self):
        while True:
            ws = None

            try:
                api_key = _get_api_key()

                ws = websocket.create_connection(
                    AIS_URL,
                    timeout=15,
                    enable_multithread=True,
                )

                # AISStream-compatible Open Waters subscription.
                ws.send(json.dumps({
                    "APIKey": api_key,
                    "BoundingBoxes": SHIPPING_LANES,
                    "FilterMessageTypes": [
                        "PositionReport",
                        "ShipStaticData",
                    ],
                }))

                ws.settimeout(10)
                self.status = "Connected; waiting for vessel reports"

                while True:
                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue

                    if not raw:
                        raise ConnectionError("AIS stream closed")

                    event = json.loads(raw)

                    # Provider error frames should be visible in the UI.
                    if event.get("error"):
                        raise RuntimeError(str(event["error"])[:200])

                    self._update_vessel(event)

            except Exception as exc:
                self.status = (
                    f"Reconnecting ({type(exc).__name__}): "
                    f"{str(exc)[:120]}"
                )
                time.sleep(5)

            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass

    def _update_vessel(self, event):
        message_type = event.get("MessageType", "")
        metadata = event.get("MetaData") or {}
        message = event.get("Message") or {}

        position = message.get("PositionReport") or {}
        static = message.get("ShipStaticData") or {}

        # PositionReport is preferred; metadata may hold a last-known position.
        lat = position.get(
            "Latitude",
            metadata.get("latitude", metadata.get("Latitude")),
        )
        lon = position.get(
            "Longitude",
            metadata.get("longitude", metadata.get("Longitude")),
        )

        mmsi = (
            metadata.get("MMSI")
            or metadata.get("MMSI_String")
            or position.get("UserID")
            or static.get("UserID")
        )

        if mmsi is None or lat is None or lon is None:
            return

        try:
            lat = float(lat)
            lon = float(lon)
        except (ValueError, TypeError):
            return

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return

        name = (
            metadata.get("ShipName")
            or static.get("Name")
            or "Unknown vessel"
        )
        name = str(name).strip().replace("@", "").strip() or "Unknown vessel"

        now = datetime.now(timezone.utc)

        # A later static-data message can update vessel details too.
        with self.lock:
            previous = self.vessels.get(str(mmsi), {})

            self.vessels[str(mmsi)] = {
                "mmsi": str(mmsi),
                "vessel": name if name != "Unknown vessel"
                          else previous.get("vessel", name),
                "latitude": lat,
                "longitude": lon,
                "speed_knots": position.get(
                    "Sog", previous.get("speed_knots")
                ),
                "course_deg": position.get(
                    "Cog", previous.get("course_deg")
                ),
                "destination": (
                    str(static.get("Destination", "")).strip()
                    or previous.get("destination", "")
                ),
                "message_type": message_type,
                "last_seen_utc": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "_updated": now.timestamp(),
            }

            # Bound memory usage in long-running sessions.
            if len(self.vessels) > 3000:
                oldest = sorted(
                    self.vessels,
                    key=lambda key: self.vessels[key]["_updated"],
                )
                for key in oldest[:len(self.vessels) - 3000]:
                    self.vessels.pop(key, None)

            self.last_message = now.strftime("%H:%M:%S UTC")
            self.status = "Receiving AIS messages"

    def get_rows(self):
        with self.lock:
            rows = [dict(v) for v in self.vessels.values()]

        rows.sort(key=lambda v: v["_updated"], reverse=True)
        return rows


@st.cache_resource(show_spinner=False)
def _get_stream():
    stream = OpenWatersVesselStream()
    stream.start()
    return stream


def render_carriers_page(*args, **kwargs):
    """Entry point called by the existing FreightQuote AI UI."""

    st.subheader("Live Carrier & Vessel Tracking")
    st.caption(
        "Open Waters AIS · Selected global shipping corridors · "
        "Live reports, subject to coverage and provider limits"
    )

    try:
        stream = _get_stream()
    except Exception as exc:
        st.error(f"Could not start the AIS stream: {exc}")
        return

    status_col, count_col, update_col = st.columns(3)

    rows = stream.get_rows()

    status_col.metric("AIS connection", "Active" if
                      stream.status == "Receiving AIS messages"
                      else "Connecting")
    count_col.metric("Vessels in cache", len(rows))
    update_col.metric("Last AIS message", stream.last_message or "Waiting")

    with st.expander("Connection details", expanded=not bool(rows)):
        st.write(stream.status)
        st.caption(
            "The map covers configured corridors, not every ocean. "
            "No vessel positions are fabricated or written to your database."
        )

    search = st.text_input(
        "Search vessel name or MMSI",
        key="openwaters_vessel_search",
    ).strip().lower()

    filtered = [
        row for row in rows
        if search in row["vessel"].lower()
        or search in row["mmsi"].lower()
    ] if search else rows

    if not filtered:
        st.info(
            "No matching vessel reports yet. AIS is event-driven; "
            "wait for reports or clear the search."
        )
        return

    map_df = pd.DataFrame([
        {
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }
        for row in filtered
    ])

    st.markdown("#### Vessel map")
    st.map(
        map_df,
        latitude="latitude",
        longitude="longitude",
        zoom=1,
        height=480,
    )

    st.markdown("#### Reported vessels")

    table_df = pd.DataFrame([
        {
            "Vessel": row["vessel"],
            "MMSI": row["mmsi"],
            "Latitude": round(row["latitude"], 6),
            "Longitude": round(row["longitude"], 6),
            "Speed (knots)": row["speed_knots"],
            "Course (degrees)": row["course_deg"],
            "Destination": row["destination"],
            "Last received (UTC)": row["last_seen_utc"],
        }
        for row in filtered
    ])

    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "AIS positions are reports received from the network, "
        "not guaranteed real-time navigation or proof of shipment delivery."
    )
