"""Synthesise the dispatcher call recordings (dev-time, once): Piper voices → one MP3 per call in public/calls/.

    pip install piper-tts av
    python scripts/build_calls.py

Voices download from the Piper project (rhasspy/piper-voices) into .cache/piper on first run.
Writes public/calls/<id>.mp3 and public/calls/index.json (title, caller, duration). The text is not stored there:
the stand transcribes the audio itself.
"""

import io
import json
import sys
import urllib.request
import wave
from pathlib import Path

import av

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.call_scripts import CALLS  # noqa: E402

CACHE = ROOT / ".cache" / "piper"
OUT = ROOT / "public" / "calls"
BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/{n}/medium/ru_RU-{n}-medium.onnx"
DISPATCHER = "irina"
_voices = {}


def voice(name):
    if name not in _voices:
        from piper import PiperVoice

        CACHE.mkdir(parents=True, exist_ok=True)
        model = CACHE / f"ru_RU-{name}-medium.onnx"
        for path, url in ((model, BASE.format(n=name)), (Path(str(model) + ".json"), BASE.format(n=name) + ".json")):
            if not path.exists():
                urllib.request.urlretrieve(url, path)
        _voices[name] = PiperVoice.load(str(model))
    return _voices[name]


def pcm(text, name):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        voice(name).synthesize_wav(text, w)
    buf.seek(0)
    with wave.open(buf) as r:
        return r.getframerate(), r.readframes(r.getnframes())


def build(call):
    rate, chunks = None, []
    for who, text in call["lines"]:
        r, frames = pcm(text, DISPATCHER if who == "d" else call["voice"])
        rate = rate or r
        assert r == rate, "voices must share the sample rate"
        chunks.append(frames + b"\x00\x00" * int(rate * 0.45))  # a short pause between turns
    raw = b"".join(chunks)
    seconds = len(raw) / 2 / rate
    out = io.BytesIO()
    with av.open(out, "w", format="mp3") as dst:
        stream = dst.add_stream("libmp3lame", rate=rate)
        stream.bit_rate = 32000
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(
            __import__("numpy").frombuffer(raw, dtype="<i2").reshape(1, -1), format="s16", layout="mono"
        )
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            dst.mux(packet)
        for packet in stream.encode(None):
            dst.mux(packet)
    (OUT / f"{call['id']}.mp3").write_bytes(out.getvalue())
    return round(seconds, 1)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for call in CALLS:
        seconds = build(call)
        index.append({"id": call["id"], "title": call["title"], "caller": call["caller"], "seconds": seconds})
        print(call["id"], seconds, "s")
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
