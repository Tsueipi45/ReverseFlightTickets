"""Manual confirmation checklist generation."""

from __future__ import annotations

from reverse_flight_tickets.domain import Offer, RiskFlag


def build_pre_purchase_checklist(offer: Offer) -> tuple[str, ...]:
    items = [
        "核对乘机人姓名、证件、航段、日期和舱位。",
        "核对付款币种、支付手续费和最终出票总价。",
        "核对行李额、退改签规则和出票平台责任边界。",
    ]
    flags = set(offer.risk_flags)
    if RiskFlag.SPLIT_TICKET in flags:
        items.append("该结果可能分开出票，确认误机和退改签不会自动保护后再购买。")
    if RiskFlag.SELF_TRANSFER in flags:
        items.append("该结果可能自转机，确认转机时间、签证和行李重新托运要求。")
    if RiskFlag.MANUAL_CHECK_REQUIRED in flags:
        items.append("该结果需要跳转人工核验，页面价格与规则可能和系统记录不同。")
    return tuple(items)
