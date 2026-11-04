from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet

from app.core.config import settings


class EncryptedLocalAudioStorage:
    """Development storage: AES/Fernet authenticated encryption at rest.

    Production deployments should use a private object store with KMS-managed keys.
    """

    def _cipher(self) -> Fernet:
        if not settings.consultation_audio_encryption_key:
            raise RuntimeError("CONSULTATION_AUDIO_ENCRYPTION_KEY is required")
        return Fernet(settings.consultation_audio_encryption_key.encode())

    def put(self, content: bytes) -> str:
        key = f"{uuid4().hex}.enc"
        root = Path(settings.consultation_audio_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        (root / key).write_bytes(self._cipher().encrypt(content))
        return key

    def get(self, key: str) -> bytes:
        if Path(key).name != key or not key.endswith(".enc"):
            raise ValueError("Invalid audio storage reference")
        return self._cipher().decrypt((Path(settings.consultation_audio_dir).resolve() / key).read_bytes())

    def delete(self, key: str) -> None:
        if Path(key).name == key and key.endswith(".enc"):
            (Path(settings.consultation_audio_dir).resolve() / key).unlink(missing_ok=True)


audio_storage = EncryptedLocalAudioStorage()
