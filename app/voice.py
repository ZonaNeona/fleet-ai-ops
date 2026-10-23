"""Speech to text for the bot, the emulator microphone and the call desk.

Any input (Telegram OGG/Opus, browser WebM, MP3) is re-encoded in memory to 16 kHz mono MP3 and sent to a
Whisper model through the same provider and the same daily budget as every other model call.
Audio is never written to disk and never logged.
"""

import base64
import io
import os
import time
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from .db import Usage, db, now

MODEL = os.getenv("STT_MODEL", "openai/whisper-large-v3-turbo")
PER_SECOND = Decimal(os.getenv("STT_PRICE_PER_SECOND", "0.00002"))  # reserve only; the provider's cost replaces it
MAX_SECONDS = 180
MAX_BYTES = 12 * 1024 * 1024


def to_mp3(raw):
    """Decode anything PyAV understands → 16 kHz mono MP3. Returns (bytes, seconds)."""
    import av

    if not raw or len(raw) > MAX_BYTES:
        raise RuntimeError("Аудио пустое или больше 12 МБ")
    out = io.BytesIO()
    samples = 0
    try:
        with av.open(io.BytesIO(raw)) as src, av.open(out, "w", format="mp3") as dst:
            stream = dst.add_stream("libmp3lame", rate=16000)
            stream.layout = "mono"
            stream.bit_rate = 32000
            resampler = av.AudioResampler(format="s16p", layout="mono", rate=16000)
            for frame in src.decode(audio=0):
                for chunk in resampler.resample(frame):
                    samples += chunk.samples
                    if samples > MAX_SECONDS * 16000:
                        raise RuntimeError(f"Запись длиннее {MAX_SECONDS} секунд")
                    for packet in stream.encode(chunk):
                        dst.mux(packet)
            for chunk in resampler.resample(None):
                samples += chunk.samples
                for packet in stream.encode(chunk):
                    dst.mux(packet)
            for packet in stream.encode(None):
                dst.mux(packet)
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("Не удалось прочитать аудио") from None
    seconds = samples / 16000
    if seconds < 0.3:
        raise RuntimeError("В записи нет звука")
    return out.getvalue(), round(seconds, 1)


def transcribe(space, raw):
    """Speech → text. The cost is reserved under the shared budget lock first, then settled from the provider."""
    from .ai import client

    if not os.getenv("OPENROUTER_API_KEY"):
        raise RuntimeError("Распознавание речи не настроено")
    mp3, seconds = to_mp3(raw)
    reserve = PER_SECOND * Decimal(str(seconds)) + Decimal("0.001")
    midnight = now().astimezone(ZoneInfo("Europe/Moscow")).replace(hour=0, minute=0, second=0, microsecond=0)
    with db() as s:
        s.execute(text("SELECT pg_advisory_xact_lock(814630)"))
        spent = s.scalar(select(func.coalesce(func.sum(Usage.cost), 0)).where(Usage.created >= midnight))
        if spent + reserve > Decimal(os.getenv("DAILY_BUDGET", ".50")):
            raise RuntimeError("Дневной лимит AI исчерпан")
        u = Usage(space=space, model=MODEL, cost=reserve)
        s.add(u)
        s.flush()
        usage_id = u.id
    started = time.monotonic()
    try:
        with client("openrouter") as c:
            r = c.post("audio/transcriptions", json={
                "model": MODEL, "language": "ru", "temperature": 0,
                "input_audio": {"data": base64.b64encode(mp3).decode("ascii"), "format": "mp3"},
            }, timeout=90)
            r.raise_for_status()
            body = r.json()
    except Exception as e:
        with db() as s:
            s.get(Usage, usage_id).cost = 0
        status = getattr(getattr(e, "response", None), "status_code", None)
        raise RuntimeError(f"Сервис распознавания речи не ответил{f' (HTTP {status})' if status else ''}") from None
    words = (body.get("text") or "").strip()
    cost = (body.get("usage") or {}).get("cost")
    ms = int((time.monotonic() - started) * 1000)
    with db() as s:
        u = s.get(Usage, usage_id)
        if cost is not None:
            u.cost = Decimal(str(cost))
        u.ms = ms
        final = str(u.cost)
    if not words:
        raise RuntimeError("Речь не распознана")
    return {"text": words[:4000], "seconds": seconds, "cost": final, "model": MODEL, "ms": ms}


def recent_count(space, hours=24):
    with db() as s:
        return s.scalar(select(func.count()).select_from(Usage).where(
            Usage.space == space, Usage.model == MODEL, Usage.created > now() - timedelta(hours=hours))) or 0
