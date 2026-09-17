from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/social_auto_agent"

    redis_url: str = "redis://localhost:6379/0"
    dispatch_interval_minutes: int = 15

    app_base_url: str = "http://localhost:8000"
    secret_key: str = "dev-secret-key-change-me"
    encryption_key: str = ""
    dev_auto_create_tables: bool = True
    jwt_access_token_expire_minutes: int = 1440

    anthropic_api_key: str = ""
    content_model: str = "claude-sonnet-5"

    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = "http://localhost:8000/auth/linkedin/callback"

    twitter_client_id: str = ""
    twitter_client_secret: str = ""
    twitter_redirect_uri: str = "http://localhost:8000/auth/twitter/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
