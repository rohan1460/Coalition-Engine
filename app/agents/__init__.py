"""Autonomous merchant agents and the negotiation protocol."""
from app.agents.agent import MerchantAgent, NegotiationContext
from app.agents.copy import generate_offer_copy
from app.agents.economics import ROLE_ECONOMICS, RoleEconomics, SkuFloor, compute_sku_floor
from app.agents.money import Proposal, compute_split
from app.agents.negotiation import (
    DEFAULT_MAX_ROUNDS,
    NegotiationEngine,
    NegotiationResult,
    new_negotiation_id,
)
from app.agents.policy import MerchantPolicy, Stance

__all__ = [
    "MerchantPolicy",
    "Stance",
    "MerchantAgent",
    "NegotiationContext",
    "Proposal",
    "compute_split",
    "NegotiationEngine",
    "NegotiationResult",
    "DEFAULT_MAX_ROUNDS",
    "new_negotiation_id",
    "generate_offer_copy",
    "SkuFloor",
    "RoleEconomics",
    "ROLE_ECONOMICS",
    "compute_sku_floor",
]
