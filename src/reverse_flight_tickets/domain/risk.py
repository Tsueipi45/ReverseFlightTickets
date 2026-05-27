"""Risk flags surfaced to users and downstream booking checks."""

from __future__ import annotations

from enum import StrEnum


class RiskFlag(StrEnum):
    SELF_TRANSFER = "self_transfer"
    SPLIT_TICKET = "split_ticket"
    NO_CHECKED_BAG_TRANSFER = "no_checked_bag_transfer"
    LONG_LAYOVER = "long_layover"
    SHORT_CONNECTION = "short_connection"
    NON_REFUNDABLE = "non_refundable"
    PROVIDER_UNVERIFIED = "provider_unverified"
    MANUAL_CHECK_REQUIRED = "manual_check_required"
    HIDDEN_CITY_EXCLUDED = "hidden_city_excluded"
