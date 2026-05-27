"""Amadeus API provider placeholder."""

from __future__ import annotations

from typing import Sequence

from reverse_flight_tickets.domain import Offer, SearchRequest
from reverse_flight_tickets.providers.base import (
    BaseProvider,
    ProviderCapability,
    ProviderContext,
    ProviderNotConfigured,
)


class AmadeusProvider(BaseProvider):
    """Reserved connector boundary for Amadeus self-service/production APIs."""

    name = "amadeus"
    capabilities = ProviderCapability(
        supports_multi_city=False,
        supports_market=True,
        supports_currency=True,
        supports_booking_link=False,
        supports_order=True,
        requires_credentials=True,
    )

    async def search(
        self,
        request: SearchRequest,
        context: ProviderContext | None = None,
    ) -> Sequence[Offer]:
        client_id = self._credential(context, "AMADEUS_CLIENT_ID")
        client_secret = self._credential(context, "AMADEUS_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise ProviderNotConfigured("Amadeus requires AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET")
        raise ProviderNotConfigured("Amadeus API client is reserved but not implemented yet")
