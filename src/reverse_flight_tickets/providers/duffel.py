"""Duffel API provider placeholder."""

from __future__ import annotations

from typing import Sequence

from reverse_flight_tickets.domain import Offer, SearchRequest
from reverse_flight_tickets.providers.base import (
    BaseProvider,
    ProviderCapability,
    ProviderContext,
    ProviderNotConfigured,
)


class DuffelProvider(BaseProvider):
    """Reserved connector boundary for Duffel sandbox/production API."""

    name = "duffel"
    capabilities = ProviderCapability(
        supports_multi_city=True,
        supports_market=True,
        supports_currency=True,
        supports_booking_link=True,
        supports_order=True,
        requires_credentials=True,
    )

    async def search(
        self,
        request: SearchRequest,
        context: ProviderContext | None = None,
    ) -> Sequence[Offer]:
        token = self._credential(context, "DUFFEL_TOKEN")
        if not token:
            raise ProviderNotConfigured("Duffel requires DUFFEL_API_TOKEN")
        raise ProviderNotConfigured("Duffel API client is reserved but not implemented yet")
