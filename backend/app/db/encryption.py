from sqlalchemy.types import TypeDecorator,Text
from cryptography.fernet import Fernet,InvalidToken
from app.core.config import settings
from datetime import date
class EncryptedText(TypeDecorator):
    impl=Text;cache_ok=False
    def _cipher(self):
        if not settings.patient_data_encryption_key:raise RuntimeError("PATIENT_DATA_ENCRYPTION_KEY is required")
        return Fernet(settings.patient_data_encryption_key.encode())
    def process_bind_param(self,value,dialect):
        if value is None:return None
        return self._cipher().encrypt(value.encode()).decode()
    def process_result_value(self,value,dialect):
        if value is None:return None
        try:return self._cipher().decrypt(value.encode()).decode()
        except (InvalidToken,ValueError) as exc:raise RuntimeError("Patient data decryption failed; verify encryption key") from exc
class EncryptedDate(EncryptedText):
    def process_bind_param(self,value,dialect):return super().process_bind_param(value.isoformat() if value else None,dialect)
    def process_result_value(self,value,dialect):
        result=super().process_result_value(value,dialect)
        return date.fromisoformat(result) if result else None
