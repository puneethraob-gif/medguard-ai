"""Run Sarvam batch STT on generated synthetic clips and write honest metrics."""
import json
import re
import sys
import unicodedata
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.consultations.providers import SarvamSpeechProvider

ROOT = Path(__file__).resolve().parent


def save_results(records):
    output = ROOT / "results.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)


def edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def normalize(text):
    text = unicodedata.normalize("NFKC", text).lower()
    return " ".join(re.findall(r"[\w]+", text, flags=re.UNICODE))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    provider = SarvamSpeechProvider()
    records = []
    for case in cases:
        audio_path = ROOT / "audio" / f"{case['id']}.wav"
        if not audio_path.exists():
            raise SystemExit(f"Missing {audio_path.name}; run generate_audio.py first.")
        result = provider.transcribe(audio_path.read_bytes(), "audio/wav", audio_path.name)
        actual = " ".join(segment.text for segment in result.segments)
        expected = " ".join(turn["text"] for turn in case["turns"])
        with wave.open(str(audio_path), "rb") as wav_file:
            audio_duration = wav_file.getnframes() / wav_file.getframerate()
        ref_words, hyp_words = normalize(expected).split(), normalize(actual).split()
        ref_chars, hyp_chars = normalize(expected).replace(" ", ""), normalize(actual).replace(" ", "")
        terms = [normalize(term) for term in case["medical_terms"]]
        joined = normalize(actual)
        segments = result.segments
        matched_terms = [term for term in terms if term in joined]
        ordered_segments = sorted(segments, key=lambda segment: segment.start_seconds)
        boundary_errors = ([abs(ordered_segments[0].start_seconds),
                            abs(audio_duration - ordered_segments[-1].end_seconds)]
                           if ordered_segments else [])
        records.append({
            "case_id": case["id"], "target_language": case["language"], "detected_language": result.detected_language,
            "language_match": result.detected_language == case["language"],
            "wer": edit_distance(ref_words, hyp_words) / max(1, len(ref_words)),
            "cer": edit_distance(ref_chars, hyp_chars) / max(1, len(ref_chars)),
            "medical_term_recall": len(matched_terms) / max(1, len(terms)),
            "matched_medical_terms": matched_terms,
            "unmatched_medical_terms": [term for term in terms if term not in matched_terms],
            "expected_speakers": case["expected_speakers"],
            "observed_speakers": len({segment.speaker_id for segment in segments if segment.speaker_id is not None}),
            "timestamped_phrases": sum(segment.end_seconds >= segment.start_seconds >= 0 for segment in segments),
            "phrase_count": len(segments),
            "audio_duration_seconds": audio_duration,
            "clip_boundary_mae_seconds": sum(boundary_errors) / len(boundary_errors) if boundary_errors else None,
            "segment_timestamps": [{"start_seconds": segment.start_seconds,
                                    "end_seconds": segment.end_seconds,
                                    "speaker_id": segment.speaker_id} for segment in segments],
            "transcript": actual,
        })
        save_results(records)
        print(json.dumps(records[-1], ensure_ascii=False))
    print(f"Wrote {ROOT / 'results.json'}; this small synthetic set is not a clinical accuracy benchmark.")


if __name__ == "__main__":
    main()
