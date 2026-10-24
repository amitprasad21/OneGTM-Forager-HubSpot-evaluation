from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    forager_api_key: str = ""
    forager_account_id: str = ""
    hubspot_access_token: str = ""
    hubspot_client_secret: str = ""

    model_config = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
    )

settings = Settings()