"""Provider terms and allowed access-mode registry."""

from __future__ import annotations

from typing import Mapping

from pydantic import BaseModel, ConfigDict


class ProviderTerms(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    access_mode: str
    production_verified: bool = False
    notes: str

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "access_mode": self.access_mode,
            "production_verified": self.production_verified,
            "notes": self.notes,
        }


class ProviderTermsRegistry(BaseModel):
    model_config = ConfigDict(frozen=True)

    providers: Mapping[str, ProviderTerms]

    def get(self, provider: str) -> ProviderTerms | None:
        return self.providers.get(provider)

    def to_dict(self) -> dict[str, object]:
        return {
            provider: terms.to_dict()
            for provider, terms in self.providers.items()
        }


def default_terms_registry() -> ProviderTermsRegistry:
    return ProviderTermsRegistry(
        providers={
            "duffel": ProviderTerms(
                provider="duffel",
                access_mode="official_api",
                production_verified=False,
                notes="Use Duffel API credentials; sandbox results may include test carriers.",
            ),
            "amadeus": ProviderTerms(
                provider="amadeus",
                access_mode="official_api",
                production_verified=False,
                notes="Use Amadeus Self-Service test or production credentials.",
            ),
            "skyscanner": ProviderTerms(
                provider="skyscanner",
                access_mode="manual_deep_link",
                production_verified=False,
                notes="Generate manual verification links only; no page scraping.",
            ),
            "trip": ProviderTerms(
                provider="trip",
                access_mode="manual_deep_link",
                production_verified=False,
                notes="Generate manual verification links only; no page scraping.",
            ),
            "fliggy": ProviderTerms(
                provider="fliggy",
                access_mode="manual_deep_link",
                production_verified=False,
                notes="Generate manual verification links only; no page scraping.",
            ),
            "google_flights_research": ProviderTerms(
                provider="google_flights_research",
                access_mode="research_manual_deep_link",
                production_verified=False,
                notes="Research-only manual link; excluded from default providers.",
            ),
            "kiwi_research": ProviderTerms(
                provider="kiwi_research",
                access_mode="research_manual_deep_link",
                production_verified=False,
                notes="Research-only manual link; excluded from default providers.",
            ),
            "letsfg_research": ProviderTerms(
                provider="letsfg_research",
                access_mode="research_placeholder",
                production_verified=False,
                notes="Reserved research connector; not enabled by default.",
            ),
        }
    )
