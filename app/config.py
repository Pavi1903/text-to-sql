from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    db_schema: str = "public"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    allowed_tables: str = ""
    max_row_limit: int = 200
    query_timeout_seconds: int = 5

    @property
    def allowed_tables_set(self) -> set[str]:
        return {t.strip() for t in self.allowed_tables.split(",") if t.strip()}


settings = Settings()
