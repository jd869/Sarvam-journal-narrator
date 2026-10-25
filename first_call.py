"""Make one small Sarvam TTS request and save a verified WAV file."""

import base64
import io
import os
from pathlib import Path
import sys
import wave

from sarvamai import SarvamAI


def main() -> int:
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not key:
        print("Missing SARVAM_API_KEY. Export it before running this script.", file=sys.stderr)
        return 1

    try:
        response = SarvamAI(api_subscription_key=key).text_to_speech.convert(
            text="Some days become memories. Today, I began saving mine.",
            model="bulbul:v4-flash",
            language_code="en-IN",
            output_audio_codec="wav",
            request_options={"max_retries": 0, "timeout_in_seconds": 90},
        )
        audio = base64.b64decode(response.audios[0], validate=True)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            frames = wav.getnframes()
            duration = frames / wav.getframerate()
            if frames == 0:
                raise ValueError("Empty WAV")
        output = Path(__file__).parent / "first_memory.wav"
        output.write_bytes(audio)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        detail = f"HTTP {status}" if status else type(exc).__name__
        print(f"TTS failed ({detail}). No automatic retry was made.", file=sys.stderr)
        return 1

    print(f"Saved {output.name} ({len(audio):,} bytes, {duration:.1f} seconds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
