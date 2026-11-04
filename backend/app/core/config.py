from pydantic import AliasChoices,Field,field_validator
from pydantic_settings import BaseSettings,SettingsConfigDict
class Settings(BaseSettings):
    app_name:str="Personal Healthcare Companion API"
    api_v1_prefix:str="/api/v1"
    database_url:str="postgresql+psycopg://healthcare@localhost:5432/healthcare_companion"
    redis_url:str="redis://localhost:6379/0"
    cors_origins:str="http://localhost:5173,http://127.0.0.1:5173,http://localhost:19006"
    jwt_secret:str=""
    access_token_minutes:int=15
    refresh_token_days:int=30
    auth_rate_limit_per_minute:int=Field(default=10,gt=0)
    auth_rate_limit_window_seconds:int=Field(default=60,gt=0)
    patient_data_encryption_key:str=""
    secure_cookies:bool=False
    consultation_audio_encryption_key:str=""
    consultation_audio_dir:str="./var/consultation-audio"
    consultation_max_audio_bytes:int=52428800
    consultation_audio_retention_days:int=30
    stt_provider:str="disabled"
    stt_api_key:str=Field(default="",validation_alias=AliasChoices("SARVAM_API_KEY","STT_API_KEY"))
    stt_base_url:str="https://api.sarvam.ai"
    stt_model:str="saaras:v4"
    stt_mode:str="codemix"
    stt_keyterms:str=""
    stt_request_timeout_seconds:int=45
    stt_batch_timeout_seconds:int=7200
    stt_max_speakers:int=2
    llm_provider:str="disabled"
    llm_api_key:str=""
    llm_base_url:str=""
    llm_model:str=""
    llm_request_timeout_seconds:int=60
    model_config=SettingsConfigDict(env_file=".env",extra="ignore")
    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_origins_with_cookie_auth(cls,value):
        origins=[item.strip() for item in value.split(",") if item.strip()]
        if "*" in origins:
            raise ValueError("CORS_ORIGINS must list explicit origins when credentials are enabled")
        return value
    @property
    def cors_origin_list(self):return [v.strip() for v in self.cors_origins.split(",") if v.strip()]
settings=Settings()
