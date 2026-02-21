# config.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from decouple import config


@dataclass(frozen=True)
class AppConfig:
    log_level: str

    translate_base_url: str
    video_base_url: str
    video_token: Optional[str]  # JWT estático; dispensa /auth/temp_login

    timeout_s: float
    poll_interval_s: float
    poll_timeout_s: float

    uf: Optional[str]
    target: Optional[str]

    out_dir: str

    @staticmethod
    def load() -> "AppConfig":
        cfg = AppConfig(
            log_level=config("LOG_LEVEL", default="INFO"),

            translate_base_url=config(
                "VLIBRAS_TRANSLATE_BASE_URL",
                default="https://traducao2.vlibras.gov.br",
            ),
            video_base_url=config("VLIBRAS_VIDEO_BASE_URL", default=""),
            video_token=config("VLIBRAS_VIDEO_TOKEN", default=None),

            timeout_s=config("VLIBRAS_TIMEOUT_S", default=30.0, cast=float),
            poll_interval_s=config("VLIBRAS_POLL_INTERVAL_S", default=3.0, cast=float),
            poll_timeout_s=config("VLIBRAS_POLL_TIMEOUT_S", default=600.0, cast=float),

            uf=config("UF", default=None),
            target=config("TARGET", default=None),

            out_dir=config("OUT_DIR", default="videos"),
        )

        if not cfg.translate_base_url.startswith(("http://", "https://")):
            raise ValueError("VLIBRAS_TRANSLATE_BASE_URL deve começar com http:// ou https://")

        if cfg.video_base_url and not cfg.video_base_url.startswith(("http://", "https://")):
            raise ValueError("VLIBRAS_VIDEO_BASE_URL deve começar com http:// ou https://")

        return cfg
        