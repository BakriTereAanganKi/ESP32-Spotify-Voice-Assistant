"""Test /voice from your laptop mic, no ESP32 needed.

pip install sounddevice requests
python test_client.py          # records 4 s, sends it, prints the reply
"""
import sys

import requests
import sounddevice as sd

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/voice"
SECONDS = 4

print(f"Speak now ({SECONDS} s)...")
audio = sd.rec(SECONDS * 16000, samplerate=16000, channels=1, dtype="int16")
sd.wait()
r = requests.post(URL, data=audio.tobytes(), headers={"Content-Type": "audio/pcm"}, timeout=60)
heard, _, reply = r.text.partition("\n")
print("heard:", heard)
print("reply:", reply)
