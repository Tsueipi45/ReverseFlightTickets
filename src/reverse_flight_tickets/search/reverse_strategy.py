"""Reverse-ticket strategy flags and risk scoring hooks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from reverse_flight_tickets.domain import Offer, RiskFlag, SearchRequest, TicketingType


class StrategyPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    return sum(weights.get(flag, 0) for flag in offer.risk_flags) + _fare_rule_risk_score(offer)


def _fare_rule_risk_score(offer: Offer) -> int:
    score = 0
    for rule in offer.fare_rules:
        if rule.refund_allowed is False:
            score += 20
        if rule.change_allowed is False:
            score += 10
        if rule.penalty_amount is not None and rule.penalty_amount > 0:
            score += 5
    return score


def apply_strategy_policy(request: SearchRequest, offers: tuple[Offer, ...]) -> tuple[Offer, ...]:
    """Apply local risk labeling and hidden-city exclusion policy."""

    return tuple(_apply_offer_policy(request, offer) for offer in offers)


def _apply_offer_policy(request: SearchRequest, offer: Offer) -> Offer:
    flags = list(offer.risk_flags)

    if offer.ticketing_type == TicketingType.SPLIT_TICKET and RiskFlag.SPLIT_TICKET not in flags:
        flags.append(RiskFlag.SPLIT_TICKET)
    if offer.ticketing_type == TicketingType.SELF_TRANSFER and RiskFlag.SELF_TRANSFER not in flags:
        flags.append(RiskFlag.SELF_TRANSFER)

    if not request.include_hidden_city and RiskFlag.HIDDEN_CITY_EXCLUDED not in flags:
        flags.append(RiskFlag.HIDDEN_CITY_EXCLUDED)

    return offer.model_copy(
        update={
            "risk_flags": tuple(flags),
        }
    )
