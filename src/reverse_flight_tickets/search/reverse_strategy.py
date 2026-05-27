"""Reverse-ticket strategy flags and risk scoring hooks."""

from __future__ import annotations

from dataclasses import dataclass

from reverse_flight_tickets.domain import Offer, RiskFlag, SearchRequest


@dataclass(frozen=True)
class StrategyPolicy:
    include_split_ticket: bool = False
    include_self_transfer: bool = False
    include_hidden_city: bool = False

    @classmethod
    def from_request(cls, request: SearchRequest) -> "StrategyPolicy":
        return cls(
            include_split_ticket=request.include_split_ticket,
            include_self_transfer=request.include_self_transfer,
            include_hidden_city=request.include_hidden_city,
        )


def risk_score(offer: Offer) -> int:
    weights = {
        RiskFlag.SELF_TRANSFER: 30,
        RiskFlag.SPLIT_TICKET: 25,
        RiskFlag.NO_CHECKED_BAG_TRANSFER: 20,
        RiskFlag.SHORT_CONNECTION: 15,
        RiskFlag.LONG_LAYOVER: 10,
        RiskFlag.NON_REFUNDABLE: 10,
        RiskFlag.PROVIDER_UNVERIFIED: 5,
        RiskFlag.MANUAL_CHECK_REQUIRED: 5,
        RiskFlag.HIDDEN_CITY_EXCLUDED: 0,
    }
    return sum(weights.get(flag, 0) for flag in offer.risk_flags)
