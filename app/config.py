from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


class Settings(BaseSettings):
    # Secrets: SecretStr keeps them out of repr(), logs and model_dump().
    forager_api_key: SecretStr = SecretStr("")
    forager_account_id: str = ""
    hubspot_access_token: SecretStr = SecretStr("")
    hubspot_client_secret: SecretStr = SecretStr("")
    admin_api_key: SecretStr = SecretStr("")

    public_base_url: str = ""
    render_external_url: str = ""  # set automatically by Render
    database_path: str = "data/app.db"
    log_level: str = "INFO"

    forager_credit_budget: int = 45
    enable_phone_lookup: bool = True
    enable_personal_email_lookup: bool = True
    enrich_extra_fields: bool = False
    max_phone_lookups_per_job: int = 2
    worker_enabled: bool = True

    discovery_titles: Annotated[list[str], NoDecode] = [
        "CEO", "CTO", "COO", "CFO", "Chief", "VP", "Vice President", "Head", "Director",
    ]
    discovery_exclude_titles: Annotated[list[str], NoDecode] = ["Intern", "Assistant"]
    discovery_max_contacts: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("discovery_titles", "discovery_exclude_titles", mode="before")
    @classmethod
    def _split_comma_separated(cls, value):
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def webhook_base_url(self) -> str:
        return (self.public_base_url or self.render_external_url).rstrip("/")

    @property
    def forager_configured(self) -> bool:
        return bool(self.forager_api_key.get_secret_value() and self.forager_account_id)

    @property
    def hubspot_configured(self) -> bool:
        return bool(self.hubspot_access_token.get_secret_value())

    def validate_required(self) -> None:
        """Raise ConfigError naming (never echoing) missing or invalid variables."""
        required = {
            "FORAGER_API_KEY": self.forager_api_key.get_secret_value(),
            "FORAGER_ACCOUNT_ID": self.forager_account_id,
            "HUBSPOT_ACCESS_TOKEN": self.hubspot_access_token.get_secret_value(),
            "HUBSPOT_CLIENT_SECRET": self.hubspot_client_secret.get_secret_value(),
            "ADMIN_API_KEY": self.admin_api_key.get_secret_value(),
        }
        problems = [f"{name} is missing" for name, value in required.items() if not value]
        if self.forager_account_id and not self.forager_account_id.isdigit():
            problems.append("FORAGER_ACCOUNT_ID must be an integer")
        if problems:
            raise ConfigError("Invalid configuration: " + "; ".join(problems))


settings = Settings()
