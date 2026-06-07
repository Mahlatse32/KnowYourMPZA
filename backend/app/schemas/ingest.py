from pydantic import BaseModel, Field, HttpUrl


class UrlBatchRequest(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1)


class IngestionSummary(BaseModel):
    processed_count: int
    created_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    errors: list[dict[str, str]]
