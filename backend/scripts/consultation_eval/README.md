# Synthetic consultation speech evaluation

`cases.json` contains fictional, non-patient utterances in Telugu, Hindi, Tamil, Kannada, Malayalam, English, Telugu-English, and Hindi-English. It includes clinical vocabulary, medicine/dosage wording, instructions, a test, follow-up, and two-speaker turns. The text is the reference transcript; generated audio is not checked in.

Generate local speech with Bulbul v3 (its documented language and classic speaker catalog includes Malayalam) and then evaluate it with Saaras v4 Batch:

```powershell
Set-Location backend
$env:STT_PROVIDER = "sarvam"
$env:SARVAM_API_KEY = "<development key from your secrets manager>"
.\.venv\Scripts\python.exe scripts\consultation_eval\generate_audio.py
.\.venv\Scripts\python.exe scripts\consultation_eval\evaluate_audio.py
```

The scripts use only the synthetic content in `cases.json`. `SARVAM_API_KEY` is preferred; the existing `STT_API_KEY` environment variable remains supported. They require provider credentials and incur TTS/STT usage charges. Audio and `results.json` stay under the ignored `audio/` evaluation directory. Metrics include per-clip WER/CER, language detection, exact normalized medical-term matches, speaker-count match, and clip-boundary timestamp error. Clip-boundary MAE compares the first/last phrase boundaries with the generated WAV duration; it does not measure internal phrase alignment or absolute diarization correctness. A clinician should additionally adjudicate dosage, negation, and instruction fidelity before drawing conclusions.

## Evaluation status

Live synthetic evaluation was run on 2026-11-04 using Bulbul v3-generated WAVs and the existing Saaras v4 batch adapter. These are eight short clips generated from reference text; they use synthetic voices and are not a clinical or accent benchmark. Mean per-clip WER was 0.0278, mean CER was 0.0218, automatic language detection matched 8/8, speaker counts matched 8/8, mean exact medical-term recall was 0.9375, and mean clip-boundary timestamp MAE was 0.182 seconds. Detailed results and transcripts are in ignored `audio/results.json`.

| Language / case | WER | CER | Language detected | Medical-term recall | Speaker count | Clip-boundary MAE |
| --- | --- | --- | --- | --- | --- | --- |
| Telugu | 0.000 | 0.000 | Match | 1.00 | 2/2 | 0.374 s |
| Hindi | 0.000 | 0.000 | Match | 1.00 | 2/2 | 0.194 s |
| Tamil | 0.000 | 0.000 | Match | 0.50 | 1/1 | 0.079 s |
| Kannada | 0.000 | 0.000 | Match | 1.00 | 1/1 | 0.161 s |
| Malayalam | 0.087 | 0.029 | Match | 1.00 | 1/1 | 0.067 s |
| English (`en-IN`) | 0.020 | 0.009 | Match | 1.00 | 2/2 | 0.153 s |
| Telugu-English | 0.000 | 0.000 | Match | 1.00 | 1/1 | 0.346 s |
| Hindi-English | 0.115 | 0.136 | Match | 1.00 | 1/1 | 0.085 s |

Tamil's exact term metric missed the expected standalone form `இரத்த அழுத்தம்` although the transcript contains the inflected form `இரத்த அழுத்தத்தை`; this demonstrates a limitation of the exact-match metric, not a confirmed transcription error. These short generated clips do not represent noise, overlapping speech, code-mixing frequency, older voices, accents, or real consultation variability. Speaker-count match does not show that speaker identities were correctly assigned. Do not use these metrics for clinical deployment approval.
