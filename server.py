"""Voice endpoint for the ESP32 remote.

ESP32 POSTs raw 16 kHz / 16-bit mono PCM to /voice.
We transcribe it with faster-whisper, hand the text to SpotifyAgent (MCP + Claude),
and return two plain-text lines: what we heard, and the short reply for the OLED.

Run:  uvicorn server:app --host 0.0.0.0 --port 8000
"""
import asyncio
import os
from contextlib import asynccontextmanager

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from faster_whisper import WhisperModel

from agent import SpotifyAgent

load_dotenv(override=True)

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en")
MIN_SAMPLES = 16000 // 3  # ignore clips shorter than ~0.33 s
PROMPT = "Spotify voice commands: play, pause, resume, next, skip, previous, volume, song, artist, album, playlist."


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    app.state.agent = SpotifyAgent()
    await app.state.agent.start()
    app.state.lock = asyncio.Lock()  # one command at a time
    print("Server ready.")
    yield
    await app.state.agent.close()


app = FastAPI(lifespan=lifespan)


def transcribe(model: WhisperModel, audio: np.ndarray) -> str:
    segments, _ = model.transcribe(
        audio,
        language="en",
        beam_size=1,
        vad_filter=True,
        initial_prompt=PROMPT,
    )
    return " ".join(s.text.strip() for s in segments).strip()


@app.post("/voice", response_class=PlainTextResponse)
async def voice(request: Request):
    pcm = await request.body()
    pcm = pcm[: len(pcm) // 2 * 2]
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if audio.size < MIN_SAMPLES or peak < 0.01:
        return "(no audio)\nDidn't catch that"
    audio = audio / peak * 0.9  # the INMP441 is quiet, so normalize

    heard = await asyncio.to_thread(transcribe, app.state.whisper, audio)
    print(f"heard: {heard!r}")
    if not heard:
        return "(nothing heard)\nTry again"

    async with app.state.lock:
        try:
            reply = await app.state.agent.ask(heard)
        except Exception as e:  # keep the ESP32 from hanging on errors
            print("agent error:", e)
            reply = "Something went wrong"
    print(f"reply: {reply!r}")
    return f"{heard}\n{reply}"


@app.get("/ping", response_class=PlainTextResponse)
async def ping():
    return "ok"
