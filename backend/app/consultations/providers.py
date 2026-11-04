"""Provider boundaries for speech recognition and structured summarisation."""
import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from typing import Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sarvamai.core.api_error import ApiError

from app.core.config import settings

# Never allow signed batch upload/download URLs to appear in HTTP request logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@dataclass
class SpeechSegment:
    text: str
    start_seconds: float
    end_seconds: float
    language_code: str | None = None
    speaker_id: str | None = None
    confidence: float | None = None


@dataclass
class SpeechResult:
    provider: str
    detected_language: str | None
    segments: list[SpeechSegment]


class SpeechRecognitionProvider(Protocol):
    def transcribe(self, audio: bytes, content_type: str, filename: str) -> SpeechResult: ...


class SummaryProvider(Protocol):
    def summarize(self, transcript: list[dict[str, Any]], history_context: str | None) -> dict[str, Any]: ...


class ProviderUnavailable(RuntimeError):
    pass


class ProviderNotConfigured(ProviderUnavailable):
    pass


class ProviderRequestError(ProviderUnavailable):
    """A provider call failed; error details must not include audio or transcript data."""


class ProviderProcessingTimeout(ProviderRequestError):
    pass


class ProviderJobFailed(ProviderRequestError):
    """A remote job is terminal; it must not be polled/re-submitted automatically."""


class SarvamSpeechProvider:
    """Official Saaras batch client; audio goes to Sarvam only after consent.

    Batch mode supports long recordings, code-mixed Indian languages, language
    detection, phrase timestamps, and optional diarization. Speaker IDs are not
    mapped to doctor/patient automatically.
    """

    def transcribe(self, audio: bytes, content_type: str, filename: str, *,
                   resume_job_id: str | None = None, resume_uploaded: bool = False,
                   resume_started: bool = False, on_job_created=None,
                   on_job_uploaded=None, on_job_started=None) -> SpeechResult:
        if not settings.stt_api_key:
            raise ProviderNotConfigured("Speech provider credentials are not configured")
        try:
            from sarvamai import SarvamAI
            from sarvamai.environment import SarvamAIEnvironment
            endpoint = settings.stt_base_url.rstrip("/")
            environment = SarvamAIEnvironment(base=endpoint, creative=endpoint, production=endpoint)
            client = SarvamAI(environment=environment, api_subscription_key=settings.stt_api_key,
                              timeout=settings.stt_request_timeout_seconds)
            private_tmp = Path(settings.consultation_audio_dir).resolve() / ".provider-work"
            private_tmp.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="consult-stt-", dir=private_tmp) as folder:
                if resume_job_id:
                    job = client.speech_to_text_job.get_job(resume_job_id)
                else:
                    job = client.speech_to_text_job.create_job(
                        model=settings.stt_model,
                        mode=settings.stt_mode,
                        language_code="unknown",
                        with_diarization=True,
                        num_speakers=settings.stt_max_speakers,
                        with_timestamps=True,
                        keyterms=_validated_keyterms(settings.stt_keyterms),
                        request_options={"timeout_in_seconds": settings.stt_request_timeout_seconds, "max_retries": 0},
                    )
                    if on_job_created:
                        on_job_created(job.job_id)
                if not resume_started:
                    if not audio:
                        raise ProviderRequestError("Audio is no longer available to finish the provider upload")
                    if not resume_uploaded:
                        extension = {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3",
                            "audio/mp4": ".m4a", "audio/aac": ".aac", "audio/ogg": ".ogg",
                            "audio/webm": ".webm", "audio/flac": ".flac", "audio/3gpp": ".3gp"}.get(content_type, ".audio")
                        path = Path(folder) / f"consultation-audio{extension}"
                        path.write_bytes(audio)
                        job.upload_files(file_paths=[str(path)], timeout=settings.stt_request_timeout_seconds)
                        if on_job_uploaded:
                            on_job_uploaded()
                    try:
                        job.start()
                    except Exception:
                        # A start response can be lost after Sarvam accepted the
                        # job. Inspect that same job ID before deciding whether a
                        # second start call is needed.
                        started_status = job.get_status()
                        if str(started_status.job_state).lower() not in {"pending", "running", "completed", "failed"}:
                            raise
                    if on_job_started:
                        on_job_started()
                status = job.wait_until_complete(poll_interval=5, timeout=settings.stt_batch_timeout_seconds)
                if str(status.job_state).lower() != "completed":
                    raise ProviderJobFailed("Speech provider batch job failed")
                results = job.get_file_results()
                if not results.get("successful"):
                    raise ProviderJobFailed("Speech provider did not return a transcript")
                # SDK download_outputs uses an unbounded httpx client for presigned URLs;
                # download explicitly with a finite timeout and verify the trusted host.
                mapping = job.get_output_mappings()[0]
                links = client.speech_to_text_job.get_download_links(
                    job_id=job.job_id, files=[mapping["output_file"]],
                    request_options={"timeout_in_seconds": settings.stt_request_timeout_seconds, "max_retries": 0},
                )
                download_url = links.download_urls[mapping["output_file"]].file_url
                parsed = urlparse(download_url)
                hostname = (parsed.hostname or "").lower().rstrip(".")
                try:
                    download_port = parsed.port
                except ValueError:
                    download_port = -1
                trusted_download_host = hostname.endswith((".amazonaws.com", ".amazonaws.com.cn"))
                if parsed.scheme != "https" or not trusted_download_host or download_port not in (None, 443):
                    raise ProviderRequestError("Speech provider returned an invalid result URL")
                response = httpx.get(download_url, timeout=settings.stt_request_timeout_seconds, follow_redirects=False)
                response.raise_for_status()
                output = response.json()
        except ProviderProcessingTimeout:
            raise
        except ProviderRequestError:
            raise
        except TimeoutError as exc:
            raise ProviderProcessingTimeout("Speech provider processing timed out") from exc
        except httpx.TimeoutException as exc:
            raise ProviderProcessingTimeout("Speech provider request timed out") from exc
        except httpx.HTTPStatusError as exc:
            # Do not expose provider response bodies, which may include request metadata.
            raise ProviderRequestError(f"Speech provider returned HTTP {exc.response.status_code}") from exc
        except ApiError as exc:
            # SDK errors can include request bodies and provider metadata; retain only
            # the status for safe troubleshooting and actionable credential/quota errors.
            status = exc.status_code
            if status in {401, 403}:
                message = "Speech provider authentication failed (HTTP 401/403)"
            elif status == 402:
                message = "Speech provider credits are insufficient (HTTP 402)"
            elif status in {400, 422}:
                message = "Speech provider rejected the audio or request (HTTP 400/422)"
            elif status is not None:
                message = f"Speech provider returned HTTP {status}"
            else:
                message = "Speech provider request failed"
            raise ProviderRequestError(message) from exc
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise ProviderRequestError("Speech provider request failed") from exc
        diarized = (output.get("diarized_transcript") or {}).get("entries") or []
        if diarized:
            segments = [SpeechSegment(
                text=item.get("transcript", ""),
                start_seconds=float(item.get("start_time_seconds", 0)),
                end_seconds=float(item.get("end_time_seconds", 0)),
                language_code=output.get("language_code"),
                speaker_id=str(item.get("speaker_id")) if item.get("speaker_id") is not None else None,
            ) for item in diarized if item.get("transcript") and item.get("start_time_seconds") is not None and item.get("end_time_seconds") is not None]
        else:
            timestamps = output.get("timestamps") or {}
            chunks = timestamps.get("chunks") or [output.get("transcript", "")]
            starts = timestamps.get("start_time_seconds") or []
            ends = timestamps.get("end_time_seconds") or []
            if len(starts) != len(chunks) or len(ends) != len(chunks):
                raise ProviderRequestError("Speech provider omitted phrase timestamps")
            segments = [SpeechSegment(text=str(text), start_seconds=float(start), end_seconds=float(end), language_code=output.get("language_code")) for text, start, end in zip(chunks, starts, ends) if text and start is not None and end is not None]
        if not segments:
            raise ProviderRequestError("Speech provider returned no usable timestamped segments")
        return SpeechResult("sarvam_saaras", output.get("language_code"), segments)


SUMMARY_FIELDS = ["chief_complaints", "symptoms", "medical_history", "doctor_observations",
    "medicines_discussed", "tests_recommended", "dietary_instructions", "dos_and_donts",
    "follow_up_recommendations", "warnings"]
_FACT_SCHEMA = {"type": "object", "required": ["text", "statement_type", "source_segment_ids"],
    "properties": {"text": {"type": "string"}, "duration": {"type": ["string", "null"]},
        "statement_type": {"enum": ["doctor_statement", "patient_statement", "ai_interpretation"]},
        "source_segment_ids": {"type": "array", "items": {"type": "integer"}}}}
SUMMARY_SCHEMA: dict[str, Any] = {"type": "object", "required": SUMMARY_FIELDS,
    "properties": {field: {"type": "array", "items": _FACT_SCHEMA} for field in SUMMARY_FIELDS}}


class SummaryFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    duration: str | None = None
    statement_type: Literal["doctor_statement", "patient_statement", "ai_interpretation"]
    source_segment_ids: list[int] = Field(min_length=1)


class ConsultationSummaryContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chief_complaints: list[SummaryFact]
    symptoms: list[SummaryFact]
    medical_history: list[SummaryFact]
    doctor_observations: list[SummaryFact]
    medicines_discussed: list[SummaryFact]
    tests_recommended: list[SummaryFact]
    dietary_instructions: list[SummaryFact]
    dos_and_donts: list[SummaryFact]
    follow_up_recommendations: list[SummaryFact]
    warnings: list[SummaryFact]


class SarvamSummaryProvider:
    """Structured JSON generation through Sarvam's chat API."""

    def summarize(self, transcript: list[dict[str, Any]], history_context: str | None) -> dict[str, Any]:
        if not settings.llm_api_key:
            raise ProviderNotConfigured("Summary provider credentials are not configured")
        try:
            from sarvamai import SarvamAI
            from sarvamai.environment import SarvamAIEnvironment
            endpoint = (settings.llm_base_url or "https://api.sarvam.ai").rstrip("/")
            environment = SarvamAIEnvironment(base=endpoint, creative=endpoint, production=endpoint)
            client = SarvamAI(environment=environment, api_subscription_key=settings.llm_api_key,
                              timeout=settings.llm_request_timeout_seconds)
            prompt = {
                "task": "Create a faithful consultation summary using only the transcript. Do not infer a diagnosis or invent missing details. Keep source segment IDs on every fact. Classify a fact as doctor_statement or patient_statement only when a source segment has that explicit speaker_role; otherwise classify it as ai_interpretation. Use empty arrays for absent information. Return only JSON matching the requested fields.",
                "transcript": transcript,
                "history_context": history_context,
                "schema": SUMMARY_SCHEMA,
            }
            response = client.chat.completions(model=settings.llm_model or "sarvam-105b", messages=[
                {"role": "system", "content": "You structure clinical dialogue. Never provide independent medical advice or add unsupported facts. Output valid JSON only."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ], response_format={"type": "json_object"}, max_tokens=6000,
                request_options={"timeout_in_seconds": settings.llm_request_timeout_seconds, "max_retries": 0})
            return json.loads(response.choices[0].message.content)
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise ProviderUnavailable("Summary provider request failed") from exc


def speech_provider() -> SpeechRecognitionProvider:
    if settings.stt_provider == "sarvam":
        return SarvamSpeechProvider()
    raise ProviderNotConfigured("Speech recognition provider is disabled")


def _validated_keyterms(value: str) -> list[str] | None:
    terms = [term.strip() for term in value.split(",") if term.strip()]
    if len(terms) > 50 or any(len(term) > 64 for term in terms):
        raise ProviderRequestError("STT_KEYTERMS exceeds provider limits (50 terms, 64 characters each)")
    return terms or None


def summary_provider() -> SummaryProvider:
    if settings.llm_provider == "sarvam":
        return SarvamSummaryProvider()
    raise ProviderUnavailable("Summary provider is disabled")
