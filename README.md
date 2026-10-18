# Voice Spotify Remote (ESP32 + MCP)

A push-to-talk voice remote for Spotify. Hold a button on an ESP32, say something like *"play something chill"* or *"skip this song"*, and your laptop transcribes it, lets Claude pick the right Spotify action through an **MCP server**, and shows the reply on a small OLED screen.

The ESP32 is a thin client. The heavy parts (speech-to-text, the AI, Spotify control) run on your laptop in Python.

## Status

| Part | State |
|---|---|
| Typed control (`agent.py` + Spotify MCP server) | Working |
| Voice server (`server.py`, Whisper + `/voice` endpoint) | Written, test with `test_client.py` |
| ESP32 firmware (`esp32_remote.ino`) | Written, not yet tested on hardware |

## How it works

```mermaid
flowchart LR
    A["ESP32 + INMP441 mic + OLED"] -- "raw audio over Wi-Fi" --> B["FastAPI /voice"]
    B --> C["faster-whisper (speech to text)"]
    C --> D["Agent (Claude)"]
    D <-- "MCP" --> E["Spotify MCP server"]
    E --> F["Spotify Web API"]
    F --> G["Phone / PC plays the music"]
    B -- "short text reply" --> A
```

1. Hold the button. The ESP32 records up to 3 seconds of 16 kHz mono audio from the I2S mic.
2. On release it POSTs the raw audio to `http://<laptop-ip>:8000/voice`.
3. The server transcribes it with `faster-whisper` and passes the text to the agent.
4. The agent (Claude) calls tools on the Spotify MCP server (play, pause, skip, volume, and so on).
5. The server returns two lines of text, what it heard and a short reply, and the ESP32 draws them on the OLED.

Music plays on whatever Spotify device is active (phone, PC, speaker). The ESP32 does not play audio; it is only a remote with a screen.

## Hardware

- ESP32 dev board (a regular ESP32 is enough, no S3 needed)
- INMP441 I2S microphone
- 0.96-inch SSD1306 OLED (I2C, 128x64)
- Push button
- USB cable or a battery pack

### Wiring

| Part | Pin | ESP32 |
|---|---|---|
| INMP441 | SCK | GPIO 26 |
| INMP441 | WS | GPIO 25 |
| INMP441 | SD | GPIO 33 |
| INMP441 | L/R | GND (selects the left channel) |
| INMP441 | VDD / GND | 3.3V / GND |
| OLED | SDA | GPIO 21 |
| OLED | SCL | GPIO 22 |
| OLED | VCC / GND | 3.3V / GND |
| Button | one leg | GPIO 4 |
| Button | other leg | GND |

## Project structure

```
.
├── agent.py                 # MCP client + Claude tool-calling loop (typed REPL)
├── spotify_mcp_server.py    # MCP server exposing Spotify tools
├── server.py                # FastAPI /voice endpoint (Whisper + agent)
├── test_client.py           # test /voice with your laptop mic, no ESP32 needed
├── esp32_remote/
│   └── esp32_remote.ino     # ESP32 firmware (Arduino)
├── requirements.txt
└── .env.example
```

## Requirements

- **Spotify Premium.** Spotify requires the developer app's owner to have Premium, and playback control is Premium-only. In development mode, search results are capped at 10 per type.
- **Python 3.12.** Newer versions (for example 3.15) have no prebuilt wheels for `av`, a dependency of `faster-whisper`, and the install fails.
- **An Anthropic API key** from [console.anthropic.com](https://console.anthropic.com). This is billed per use and is separate from a Claude.ai subscription.
- **Arduino IDE** with ESP32 board support (core 3.x) and the *Adafruit SSD1306* and *Adafruit GFX Library* libraries.

## Setup (laptop)

### 1. Create a Spotify app

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and create an app that uses the **Web API**.
2. Add this redirect URI: `http://127.0.0.1:8888/callback` (Spotify wants the explicit `127.0.0.1`, not `localhost`).
3. Copy the client ID and client secret.

### 2. Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` pins `mcp<2` because this code uses the 1.x API (`FastMCP`).

### 3. Configure

```bash
cp .env.example .env
```

Fill in `.env`:

```
SPOTIPY_CLIENT_ID=...
SPOTIPY_CLIENT_SECRET=...
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-haiku-5-5
WHISPER_MODEL=base.en
```

`WHISPER_MODEL=small.en` is slower but more accurate if song names get misheard.

### 4. Log in to Spotify (once)

```bash
python spotify_mcp_server.py --login
```

A browser tab opens. Approve access, and the token is saved to `.spotify_cache`.

### 5. Try typed commands

Open Spotify on your phone or PC and play any song once, so there is an active device. Then:

```bash
python agent.py
```

Try `play yellow by coldplay`, `pause`, `volume 30`, `what's playing`.

### 6. Start the voice server

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

The first start downloads the Whisper model. Wait for `Server ready.`

### 7. Test voice without the ESP32

In a second terminal (venv activated):

```bash
pip install sounddevice requests
python test_client.py
```

Speak for 4 seconds. It prints what it heard and the reply. macOS asks for microphone permission for the terminal the first time.

## Setup (ESP32)

1. Open `esp32_remote/esp32_remote.ino` in the Arduino IDE.
2. Edit `WIFI_SSID`, `WIFI_PASS` and `SERVER_URL` at the top. Use your laptop's local IP, and make sure both devices are on the same Wi-Fi.
3. Select **ESP32 Dev Module**, flash it, and open the Serial Monitor at 115200 baud.
4. Hold the button, talk, release. The OLED shows *Listening...*, *Thinking...*, then what it heard and the reply.

Do not commit your Wi-Fi password. Keep real credentials out of the repository.

## MCP tools

| Tool | What it does |
|---|---|
| `search_and_play` | Search and play a track, artist, album or playlist |
| `queue_track` | Add a track to the queue |
| `pause` / `resume` | Pause or resume playback |
| `next_track` / `previous_track` | Skip forward or back |
| `set_volume` | Set volume from 0 to 100 |
| `now_playing` | Report the current track and volume |
| `list_devices` | List available Spotify devices |

## Troubleshooting

| Problem | Fix |
|---|---|
| `pip install` fails building `av` | You are on a Python that is too new. Use Python 3.12 and recreate the venv. |
| `No module named 'mcp.server.fastmcp'` | mcp 2.x is installed. Run `pip install "mcp<2"`. |
| `401 invalid x-api-key` | The key is wrong, or an old `ANTHROPIC_API_KEY` is exported in your shell. Run `unset ANTHROPIC_API_KEY`. The code loads `.env` with `override=True`. |
| "No active Spotify device" | Open Spotify on a phone or PC and play something once. |
| Spotify returns 403 | The Spotify app owner needs Premium, or the endpoint is restricted in development mode. |
| `command not found: python` | Activate the venv first with `source .venv/bin/activate`. |
| Transcription is empty or wrong | Check the mic wiring (L/R to GND). Lower `GAIN_SHIFT` in the sketch for more volume, or switch `I2S_STD_SLOT_LEFT` to `RIGHT`. Try `WHISPER_MODEL=small.en`. |
| OLED stays blank | The I2C address may be `0x3D` instead of `0x3C`. |
| ESP32 cannot reach the server | Check the laptop's IP in `SERVER_URL`, that both are on the same Wi-Fi, and that the firewall allows port 8000. |
