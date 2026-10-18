"""Spotify MCP server for the ESP32 voice remote.

First time only:  python spotify_mcp_server.py --login
After that, agent.py starts this file automatically (over stdio).
"""
import functools
import sys
from pathlib import Path

import spotipy
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

SCOPE = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
KINDS = {"track", "artist", "album", "playlist"}

# Reads SPOTIPY_CLIENT_ID / SPOTIPY_CLIENT_SECRET / SPOTIPY_REDIRECT_URI from .env
auth = SpotifyOAuth(scope=SCOPE, cache_path=str(HERE / ".spotify_cache"), open_browser=True)

mcp = FastMCP("spotify-esp32")
_client = None


def sp() -> spotipy.Spotify:
    global _client
    if _client is None:
        # Never start an interactive login here: stdio is used by MCP.
        if auth.cache_handler.get_cached_token() is None:
            raise RuntimeError("Not logged in. Run: python spotify_mcp_server.py --login")
        _client = spotipy.Spotify(auth_manager=auth)
    return _client


def safe(fn):
    """Turn Spotify errors into short messages the AI (and the OLED) can use."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SpotifyException as e:
            if e.reason == "NO_ACTIVE_DEVICE" or e.http_status == 404:
                return "No active Spotify device. Open Spotify on your phone or PC and play something once."
            if e.http_status == 403:
                return "Spotify refused this (403). Premium is required, or the endpoint is restricted."
            if e.http_status == 429:
                return "Spotify rate limit hit. Try again in a moment."
            return f"Spotify error {e.http_status}."

    return wrapper


def _device_id():
    """If nothing is active but a device exists, target it so playback can start."""
    devices = sp().devices().get("devices", [])
    if not devices or any(d["is_active"] for d in devices):
        return None
    return devices[0]["id"]


def _find(query: str, kind: str):
    res = sp().search(q=query, type=kind, limit=5)
    items = [i for i in res[f"{kind}s"]["items"] if i]  # Spotify can return null items
    return items[0] if items else None


@mcp.tool()
@safe
def search_and_play(query: str, kind: str = "track") -> str:
    """Search Spotify and start playing the best match.
    kind: 'track' (default), 'artist', 'album' or 'playlist'.
    For moods or vague requests (e.g. 'something chill'), search for a fitting
    keyword such as 'chill' or 'lofi beats' with kind='playlist' or 'track'."""
    kind = kind.lower()
    if kind not in KINDS:
        return "kind must be track, artist, album or playlist."
    item = _find(query, kind)
    if not item:
        return f"No {kind} found for '{query}'."
    if kind == "track":
        sp().start_playback(device_id=_device_id(), uris=[item["uri"]])
        who = ", ".join(a["name"] for a in item["artists"])
        return f"Playing {item['name']} by {who}"
    sp().start_playback(device_id=_device_id(), context_uri=item["uri"])
    return f"Playing {kind} {item['name']}"


@mcp.tool()
@safe
def queue_track(query: str) -> str:
    """Search for a track and add it to the end of the queue."""
    item = _find(query, "track")
    if not item:
        return f"No track found for '{query}'."
    sp().add_to_queue(item["uri"], device_id=_device_id())
    return f"Queued {item['name']}"


@mcp.tool()
@safe
def pause() -> str:
    """Pause playback."""
    sp().pause_playback()
    return "Paused"


@mcp.tool()
@safe
def resume() -> str:
    """Resume playback."""
    sp().start_playback(device_id=_device_id())
    return "Resumed"


@mcp.tool()
@safe
def next_track() -> str:
    """Skip to the next track."""
    sp().next_track(device_id=_device_id())
    return "Skipped to next"


@mcp.tool()
@safe
def previous_track() -> str:
    """Go back to the previous track."""
    sp().previous_track(device_id=_device_id())
    return "Went to previous"


@mcp.tool()
@safe
def set_volume(percent: int) -> str:
    """Set the volume from 0 to 100."""
    percent = max(0, min(100, percent))
    sp().volume(percent, device_id=_device_id())
    return f"Volume {percent}%"


@mcp.tool()
@safe
def now_playing() -> str:
    """Say what is currently playing and the volume."""
    state = sp().current_playback()
    if not state or not state.get("item"):
        return "Nothing is playing."
    item = state["item"]
    who = ", ".join(a["name"] for a in item.get("artists", []))
    status = "Playing" if state["is_playing"] else "Paused"
    vol = (state.get("device") or {}).get("volume_percent")
    return f"{status}: {item['name']} by {who}, volume {vol}%"


@mcp.tool()
@safe
def list_devices() -> str:
    """List Spotify devices that can play music."""
    devices = sp().devices().get("devices", [])
    if not devices:
        return "No devices found. Open Spotify on your phone or PC."
    return "; ".join(f"{d['name']}{' (active)' if d['is_active'] else ''}" for d in devices)


def login():
    spotipy.Spotify(auth_manager=auth).devices()  # triggers the browser login, caches the token
    print("Logged in. Token saved to .spotify_cache")


if __name__ == "__main__":
    if "--login" in sys.argv:
        login()
    else:
        mcp.run()  # stdio transport
