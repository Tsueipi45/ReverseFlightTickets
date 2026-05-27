"""Provider interfaces and shared base classes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence, runtime_checkable

from reverse_flight_tickets.domain import Offer, ProviderQuote, RiskFlag, SearchRequest, TicketingType


@dataclass(frozen=True)
class ProviderCapability:
    """Feature flags advertised by each connector."""

    supports_multi_city: bool = False
    supports_market: bool = False
    supports_currency: bool = False
    supports_booking_link: bool = False
    supports_order: bool = False
    supports_deep_link: bool = False
    requires_credentials: bool = False
    is_research: bool = False


@dataclass(frozen=True)
class ProviderContext:
    """Runtime material passed from orchestrator into provider connectors."""

    credentials: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 20.0
    metadata: Mapping[str, str] = field(default_factory=dict)


class ProviderError(RuntimeError):
    """Base error for provider-specific failures."""


class ProviderNotConfigured(ProviderError):
    """Raised when a provider requires credentials or setup that is not present."""


@runtime_checkable
class FlightProvider(Protocol):
    """Protocol every future provider connector must implement."""

    name: str
    capabilities: ProviderCapability

    async def search(
        self,
        request: SearchRequest,
        context: ProviderContext | None = None,
    ) -> Sequence[Offer]:
        """Return normalized offers for a canonical search request."""


class BaseProvider:
    """Base class for concrete API provider connectors."""

    name = "base"
    capabilities = ProviderCapability()

    async def search(
        self,
        request: SearchRequest,
        context: ProviderContext | None = None,
    ) -> Sequence[Offer]:
        raise NotImplementedError

    def _credential(self, context: ProviderContext | None, key: str) -> str | None:
        if context is None:
            return None
        return context.credentials.get(key)

    def _first_market(self, request: SearchRequest) -> str:
        return request.allowed_markets[0]

    def _first_currency(self, request: SearchRequest) -> str:
        return request.allowed_currencies[0]


class ManualDeepLinkProvider(BaseProvider):
    """Provider that returns a manual verification link without scraping pages."""

    capabilities = ProviderCapability(
        supports_market=True,
        supports_currency=True,
        supports_booking_link=True,
        supports_deep_link=True,
    )

    async def search(
        self,
        request: SearchRequest,
        context: ProviderContext | None = None,
    ) -> Sequence[Offer]:
        booking_link = self.build_booking_link(request)
        quote = ProviderQuote(
            provider=self.name,
            status="manual_check_required",
            raw={"booking_link": booking_link, "request": request.to_dict()},
        )
        return (
            Offer(
                provider=self.name,
                source_market=self._first_market(request),
                currency=self._first_currency(request),
                total_amount=None,
                comparable_amount=None,
                segments=request.segments,
                ticketing_type=TicketingType.MANUAL_CHECK,
                booking_link=booking_link,
                risk_flags=(RiskFlag.PROVIDER_UNVERIFIED, RiskFlag.MANUAL_CHECK_REQUIRED),
                provider_quote=quote,
                manual_check_required=True,
            ),
        )

    def build_booking_link(self, request: SearchRequest) -> str:
        raise NotImplementedError
