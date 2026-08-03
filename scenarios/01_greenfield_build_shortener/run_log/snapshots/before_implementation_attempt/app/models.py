"""Pydantic request/response schemas for the URL shortener API."""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ShortenRequest(BaseModel):
    long_url: str = Field(..., description="The URL to shorten. Must start with http:// or https://")

    @field_validator("long_url")
    @classmethod
    def validate_long_url(cls, value: str) -> str:
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("long_url must start with http:// or https://")
        if len(value) > 2048:
            raise ValueError("long_url is too long (max 2048 characters)")
        return value


class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    long_url: str


class AnalyticsResponse(BaseModel):
    short_code: str
    long_url: str
    created_at: str
    last_accessed_at: Optional[str] = None
    clicks: int
    recent_hits: List[str]
