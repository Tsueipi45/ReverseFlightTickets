"""LetsFG research connector placeholder."""

from __future__ import annotations

from typing import Sequence

from reverse_flight_tickets.domain import Offer, SearchRequest
from reverse_flight_tickets.providers.base import (
    BaseProvider,
    ProviderCapability,
    ProviderContext,
    ProviderNotConfigured,
)


class LetsFGResearchProvider(BaseProvider):
    """Reserved boundary for experimenting with LetsFG-style tooling."""

    name = "letsfg_research"
    capabilities = ProviderCapability(is_research=True)

    async def search(
        self,
        request: SearchRequest,
        context: ProviderContext | None = None,
    ) -> Sequence[Offer]:
        raise ProviderNotConfigured("LetsFG research connector is reserved but not implemented yet")
