from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "KnowYourMPZA"
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    database_url: str = Field(
        default="postgresql+psycopg://knowyourmpza:knowyourmpza@localhost:5432/knowyourmpza",
        validation_alias="DATABASE_URL",
    )
    cors_origin: str = Field(default="http://localhost:5173,http://localhost:3000", validation_alias="CORS_ORIGIN")
    people_assembly_base_url: str = Field(default="https://www.pa.org.za", validation_alias="PEOPLE_ASSEMBLY_BASE_URL")
    people_assembly_member_list_urls: str = Field(
        default="https://www.pa.org.za/position/member/parliament/",
        validation_alias="PEOPLE_ASSEMBLY_MEMBER_LIST_URLS",
    )
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5-mini", validation_alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in {"development", "dev", "local"}

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origin.split(",") if origin.strip()]

    @property
    def people_assembly_listing_urls(self) -> list[str]:
        return [url.strip() for url in self.people_assembly_member_list_urls.split(",") if url.strip()]


settings = Settings()
