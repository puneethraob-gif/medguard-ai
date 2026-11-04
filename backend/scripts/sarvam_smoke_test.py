"""Make one real Saaras v4 request using the existing adapter and synthetic WAV."""
import argparse
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.consultations.providers import (
    ProviderJobFailed,
    ProviderNotConfigured,
    ProviderProcessingTimeout,
    ProviderRequestError,
    SarvamSpeechProvider,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True, help="Path to a short synthetic WAV (no patient audio).")
    args = parser.parse_args()
    try:
        wav_path = args.audio.resolve()
        if not wav_path.is_file() or wav_path.stat().st_size < 128:
            raise ValueError("The supplied synthetic WAV is missing or empty.")
        try:
            with wave.open(str(wav_path), "rb") as audio_file:
                if audio_file.getnframes() < 1 or audio_file.getframerate() < 1:
                    raise ValueError("The supplied WAV contains no audio frames.")
        except wave.Error as exc:
            raise ValueError("The supplied file is not a valid WAV audio sample.") from exc
        result = SarvamSpeechProvider().transcribe(
            wav_path.read_bytes(), "audio/wav", wav_path.name
        )
        print(f"provider: {result.provider}")
        print(f"detected_language: {result.detected_language or 'unknown'}")
        for segment in result.segments:
            print(
                f"[{segment.start_seconds:.2f}-{segment.end_seconds:.2f}s] "
                f"{segment.text}"
            )
        return 0
    except ProviderNotConfigured:
        print("Sarvam credentials are not configured; set SARVAM_API_KEY in backend/.env.", file=sys.stderr)
        return 2
    except ProviderProcessingTimeout:
        print("Sarvam transcription timed out; inspect the saved provider job before retrying.", file=sys.stderr)
        return 3
    except ProviderJobFailed:
        print("Sarvam returned no successful transcript. Check that the synthetic WAV is valid and non-empty.", file=sys.stderr)
        return 4
    except ProviderRequestError as exc:
        print(str(exc), file=sys.stderr)
        return 5
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 6
    except Exception as exc:
        print(f"Smoke test failed ({type(exc).__name__}); no credential or response body was printed.", file=sys.stderr)
        return 7


if __name__ == "__main__":
    raise SystemExit(main())
