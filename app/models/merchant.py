"""Merchant schema — a store and its catalog."""
from pydantic import BaseModel, Field

from app.models.product import Product


class Merchant(BaseModel):
    merchant_id: str = Field(..., description="Unique merchant identifier.")
    name: str
    category: str
    description: str = ""
    products: list[Product] = Field(default_factory=list)

    # Razorpay Route linked-account id (TEST MODE), populated at integration
    # time. Optional so catalogs can be loaded without payment wiring.
    razorpay_account_id: str | None = Field(
        default=None,
        description="Razorpay Route linked account id (acc_...), test mode.",
    )
