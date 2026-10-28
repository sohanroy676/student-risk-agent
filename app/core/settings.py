from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime config; values come from the environment or `.env`, never from source."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    redis_url: str = ""
    app_env: str = "dev"
    app_timezone: str = "UTC"
    csv_dir: str = ""
    model_store: str = "mlruns"


def get_settings() -> Settings:
    return Settings()
