import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Config(BaseModel, extra="forbid"):
    celex: str = Field("32024R1991", pattern=r"^3\d{4}[RL]\d{4}$")
    article: str = Field("20", pattern=r"^\d+$")
    language: str = Field("eng", pattern=r"^eng$")
    cordis_limit: int = Field(1000, ge=1, le=25000)
    cdse_pages: int = Field(12, ge=1, le=50)
    cdse_collection_ids: list[str] = Field(default_factory=list, max_length=20)
    cmr_pages: int = Field(1, ge=1, le=10)
    cmr_page_size: int = Field(25, ge=1, le=100)
    cmr_keywords: list[str] = Field(default_factory=lambda: ["vegetation", "land cover"])
    timeout_seconds: float = Field(30, gt=0, le=60)
    source_budget_seconds: float = Field(150, gt=0, le=600)
    retries: int = Field(3, ge=0, le=3)
    encoder_threads: int = Field(4, ge=1, le=16)
    encoder_batch: int = Field(24, ge=1, le=128)

    @classmethod
    def read(cls, path: Path) -> "Config":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def artifacts() -> Path:
    return Path(os.environ.get("EUPOLICYEO_ARTIFACTS", "artifacts")).resolve()


def tracking_uri() -> str:
    return os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
