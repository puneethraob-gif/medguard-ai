import json
from types import SimpleNamespace

import pytest

from app.consultations.providers import (ProviderProcessingTimeout, ProviderRequestError,
    ProviderNotConfigured, SarvamSpeechProvider, SarvamSummaryProvider, speech_provider)
from app.core.config import settings
from sarvamai.core.api_error import ApiError


def install_fake_sarvam(monkeypatch, output, *, simulate_timeout=False, download_url="https://synthetic-bucket.s3.ap-south-1.amazonaws.com/result"):
    calls = {}

    class FakeJob:
        job_id = "sarvam-job-synthetic"
        def upload_files(self, file_paths, timeout):
            from pathlib import Path
            calls["uploaded"] = Path(file_paths[0]).read_bytes()
            calls["upload_timeout"] = timeout
        def start(self): calls["started"] = True
        def wait_until_complete(self, poll_interval, timeout):
            calls["poll"] = (poll_interval, timeout)
            if simulate_timeout:
                raise TimeoutError("synthetic timeout")
            return SimpleNamespace(job_state="Completed")
        def get_file_results(self): return {"successful": [{"output_file": "0.json"}], "failed": []}
        def get_output_mappings(self): return [{"input_file": "consultation.wav", "output_file": "0.json"}]

    class FakeBatch:
        def create_job(self, **kwargs):
            calls["create"] = kwargs
            return FakeJob()
        def get_job(self, job_id):
            calls["resume"] = job_id
            return FakeJob()
        def get_download_links(self, **kwargs):
            calls["download_links"] = kwargs
            return SimpleNamespace(download_urls={"0.json": SimpleNamespace(file_url=download_url)})

    class FakeClient:
        def __init__(self, **kwargs): calls["client"] = kwargs; self.speech_to_text_job = FakeBatch()

    import sarvamai
    monkeypatch.setattr(sarvamai, "SarvamAI", FakeClient)
    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return output
    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: (calls.update({"download": (url, kwargs)}) or FakeResponse()))
    monkeypatch.setattr(settings, "stt_api_key", "synthetic-test-key")
    monkeypatch.setattr(settings, "stt_keyterms", "paracetamol,CBC")
    monkeypatch.setattr(settings, "stt_batch_timeout_seconds", 90)
    return calls


def test_sarvam_batch_sends_audio_and_preserves_language_speakers_timestamps(monkeypatch):
    calls = install_fake_sarvam(monkeypatch, {
        "transcript": "मुझे cough है", "language_code": "hi-IN",
        "diarized_transcript": {"entries": [{"transcript": "मुझे cough है", "start_time_seconds": 0.4,
            "end_time_seconds": 1.8, "speaker_id": "1"}]},
    })
    result = SarvamSpeechProvider().transcribe(b"synthetic-audio", "audio/wav", "../patient-name.wav")
    assert result.detected_language == "hi-IN"
    assert [(s.text, s.start_seconds, s.end_seconds, s.speaker_id) for s in result.segments] == [("मुझे cough है", 0.4, 1.8, "1")]
    assert calls["uploaded"] == b"synthetic-audio"
    assert calls["create"]["mode"] == "codemix" and calls["create"]["language_code"] == "unknown"
    assert calls["create"]["with_diarization"] and calls["create"]["with_timestamps"]
    assert calls["create"]["keyterms"] == ["paracetamol", "CBC"]
    assert calls["create"]["request_options"]["max_retries"] == 0
    assert calls["download"][1]["timeout"] == settings.stt_request_timeout_seconds


def test_sarvam_batch_timeout_is_reported_and_job_can_be_resumed(monkeypatch):
    calls = install_fake_sarvam(monkeypatch, {}, simulate_timeout=True)
    with pytest.raises(ProviderProcessingTimeout):
        SarvamSpeechProvider().transcribe(b"audio", "audio/wav", "clip.wav", on_job_created=lambda job_id: calls.update({"persisted": job_id}))
    assert calls["persisted"] == "sarvam-job-synthetic"
    assert calls["poll"] == (5, 90)
    # A later bounded retry continues the same provider job, never creates another.
    output = {"transcript": "hello", "language_code": "en-IN", "timestamps": {"chunks": ["hello"], "start_time_seconds": [0], "end_time_seconds": [1]}}
    resumed = install_fake_sarvam(monkeypatch, output)
    SarvamSpeechProvider().transcribe(b"ignored", "audio/wav", "clip.wav", resume_job_id="sarvam-job-synthetic")
    assert resumed["resume"] == "sarvam-job-synthetic" and "create" not in resumed


def test_sarvam_rejects_untrusted_download_url_and_missing_timestamps(monkeypatch):
    output = {"transcript": "hello", "language_code": "en-IN", "timestamps": {"chunks": ["hello"], "start_time_seconds": [], "end_time_seconds": []}}
    install_fake_sarvam(monkeypatch, output, download_url="https://attacker.example/file")
    with pytest.raises(ProviderRequestError, match="invalid result URL"):
        SarvamSpeechProvider().transcribe(b"audio", "audio/wav", "clip.wav")
    install_fake_sarvam(monkeypatch, output)
    with pytest.raises(ProviderRequestError, match="omitted phrase timestamps"):
        SarvamSpeechProvider().transcribe(b"audio", "audio/wav", "clip.wav")


@pytest.mark.parametrize(("status", "message"), [
    (401, "authentication failed"), (403, "authentication failed"),
    (402, "credits are insufficient"), (400, "rejected the audio"),
    (422, "rejected the audio"),
])
def test_sarvam_sdk_errors_are_classified_without_leaking_provider_body(monkeypatch, status, message):
    class FakeBatch:
        def create_job(self, **kwargs):
            raise ApiError(status_code=status, body={"secret_detail": "must not leak"})
    class FakeClient:
        def __init__(self, **kwargs): self.speech_to_text_job = FakeBatch()
    import sarvamai
    monkeypatch.setattr(sarvamai, "SarvamAI", FakeClient)
    monkeypatch.setattr(settings, "stt_api_key", "synthetic-test-key")
    with pytest.raises(ProviderRequestError, match=message) as exc:
        SarvamSpeechProvider().transcribe(b"synthetic-audio", "audio/wav", "clip.wav")
    assert "must not leak" not in str(exc.value)


def test_sarvam_api_key_aliases_preserve_legacy_environment_name(monkeypatch):
    from app.core.config import Settings
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    monkeypatch.delenv("STT_API_KEY", raising=False)
    monkeypatch.setenv("SARVAM_API_KEY", "new-name-test-value")
    assert Settings(_env_file=None).stt_api_key == "new-name-test-value"
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    monkeypatch.setenv("STT_API_KEY", "legacy-name-test-value")
    assert Settings(_env_file=None).stt_api_key == "legacy-name-test-value"


def test_disabled_provider_fails_closed_without_mock_transcription(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "disabled")
    with pytest.raises(ProviderNotConfigured):
        speech_provider()


def test_sarvam_summary_adapter_sends_only_transcript_and_requires_json(monkeypatch):
    fact = {"text": "Paracetamol 500 mg twice daily", "statement_type": "doctor_statement", "source_segment_ids": [4]}
    content = {"chief_complaints": [], "symptoms": [], "medical_history": [], "doctor_observations": [],
        "medicines_discussed": [fact], "tests_recommended": [], "dietary_instructions": [], "dos_and_donts": [],
        "follow_up_recommendations": [], "warnings": []}
    calls = {}
    class FakeChat:
        def completions(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(content)))])
    class FakeClient:
        def __init__(self, **kwargs): calls["client"] = kwargs; self.chat = FakeChat()
    import sarvamai
    monkeypatch.setattr(sarvamai, "SarvamAI", FakeClient)
    monkeypatch.setattr(settings, "llm_api_key", "synthetic-summary-key")
    monkeypatch.setattr(settings, "llm_request_timeout_seconds", 40)
    transcript = [{"id": 4, "text": "Take paracetamol 500 mg twice daily", "speaker_role": "doctor", "start_seconds": 2.0}]
    result = SarvamSummaryProvider().summarize(transcript, None)
    assert result == content
    prompt = json.loads(calls["messages"][1]["content"])
    assert prompt["transcript"] == transcript and "patient_profile" not in prompt
    assert calls["response_format"] == {"type": "json_object"}
    assert calls["request_options"]["max_retries"] == 0
    assert calls["request_options"]["timeout_in_seconds"] == 40

