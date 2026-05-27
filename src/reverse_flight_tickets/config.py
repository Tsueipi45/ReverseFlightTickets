"""Application configuration and provider credential loading."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Mapping


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return tuple(part.strip().upper() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class ProviderCredential:
    """Credential material for a future API provider connector."""

    provider: str
    token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    extra: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        return any((self.token, self.client_id, self.client_secret, self.extra))


@dataclass(frozen=True)
class AppConfig:
    """Runtime settings consumed by CLI, orchestrator, and providers."""

    default_markets: tuple[str, ...] = ("US",)
    default_currencies: tuple[str, ...] = ("USD",)
    provider_timeout_seconds: float = 20.0
    credentials: Mapping[str, ProviderCredential] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "AppConfig":
        credentials = {
            "duffel": ProviderCredential(
                provider="duffel",
                token=os.getenv("DUFFEL_API_TOKEN") or None,
            ),
            "amadeus": ProviderCredential(
                provider="amadeus",
                client_id=os.getenv("AMADEUS_CLIENT_ID") or None,
                client_secret=os.getenv("AMADEUS_CLIENT_SECRET") or None,
            ),
            "skyscanner": ProviderCredential(
                provider="skyscanner",
                token=os.getenv("SKYSCANNER_API_KEY") or None,
            ),
            "trip": ProviderCredential(
                provider="trip",
                token=os.getenv("TRIP_API_KEY") or None,
            ),
            "fliggy": ProviderCredential(
                provider="fliggy",
                client_id=os.getenv("FLIGGY_APP_KEY") or None,
                client_secret=os.getenv("FLIGGY_APP_SECRET") or None,
            ),
        }
        return cls(
            default_markets=_csv_env("RFT_DEFAULT_MARKETS", ("US",)),
            default_currencies=_csv_env("RFT_DEFAULT_CURRENCIES", ("USD",)),
            provider_timeout_seconds=float(os.getenv("RFT_PROVIDER_TIMEOUT_SECONDS", "20")),
            credentials=credentials,
        )

    def provider_secret_map(self) -> dict[str, str]:
        """Flatten configured credentials into the key/value shape expected by providers."""

        secrets: dict[str, str] = {}
        for credential in self.credentials.values():
            prefix = credential.provider.upper()
            if credential.token:
                secrets[f"{prefix}_TOKEN"] = credential.token
            if credential.client_id:
                secrets[f"{prefix}_CLIENT_ID"] = credential.client_id
            if credential.client_secret:
                secrets[f"{prefix}_CLIENT_SECRET"] = credential.client_secret
            for key, value in credential.extra.items():
                secrets[f"{prefix}_{key.upper()}"] = value
        return secrets
