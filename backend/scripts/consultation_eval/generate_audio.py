"""Generate non-clinical synthetic speech clips using Sarvam TTS for evaluation."""
import base64
import json
import os
import sys
import wave
from io import BytesIO
from pathlib import Path

from sarvamai import SarvamAI

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT.parents[1]
sys.path.insert(0, str(BACKEND))
from app.core.config import settings

OUT = ROOT / "audio"


def main():
    api_key = os.environ.get("SARVAM_API_KEY") or os.environ.get("STT_API_KEY") or settings.stt_api_key
    if not api_key:
        raise SystemExit("Set STT_API_KEY in the environment; no audio was generated.")
    client = SarvamAI(api_subscription_key=api_key, timeout=45)
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    for case in cases:
        frames = []
        params = []
        for turn in case["turns"]:
            voice = turn.get("voice", case["voice"])
            result = client.text_to_speech.convert(text=turn["text"], language_code=case["language"],
                speaker=voice, model=case.get("tts_model", "bulbul:v3"), output_audio_codec="wav",
                speech_sample_rate=16000, request_options={"timeout_in_seconds": 45, "max_retries": 0})
            pcm = base64.b64decode(result.audios[0])
            with wave.open(BytesIO(pcm), "rb") as audio:
                params.append(audio.getparams())
                frames.append(audio.readframes(audio.getnframes()))
        if not frames or any((p.nchannels, p.sampwidth, p.framerate, p.comptype, p.compname) !=
                             (params[0].nchannels, params[0].sampwidth, params[0].framerate, params[0].comptype, params[0].compname)
                             for p in params):
            raise RuntimeError(f"Inconsistent synthesized WAV format for {case['id']}")
        # Add a short pause between turns. The batch recognizer receives a single WAV.
        silence = b"\0" * int(params[0].framerate * 0.35) * params[0].sampwidth * params[0].nchannels
        with wave.open(str(OUT / f"{case['id']}.wav"), "wb") as output:
            output.setparams(params[0])
            output.writeframes(silence.join(frames))
        print(f"generated {case['id']}.wav")


if __name__ == "__main__":
    main()
