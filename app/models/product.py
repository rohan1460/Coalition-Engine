"""Product schema — one item in a merchant's catalog."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# "anchor"    — the high-value item that drives the purchase (thin, competitive
#               retail margins; won't discount much even in a coalition deal).
# "companion" — the attach item riding along on someone else's traffic (fat
#               accessory-category margins; has real room to discount).
ProductRole = Literal["anchor", "companion"]


class Product(BaseModel):
    product_id: str = Field(..., description="Unique product identifier.")
    merchant_id: str = Field(..., description="Owning merchant's identifier.")
    name: str
    description: str = Field(
        ...,
        description="Rich, detailed description used for semantic embedding.",
    )
    category: str
    price_inr: int = Field(..., ge=0, description="Selling price in whole INR.")
    cost_price_inr: int = Field(
        ..., ge=0,
        description=(
            "What the merchant paid for this unit. The hard floor on any "
            "coalition discount is derived from price_inr - cost_price_inr — "
            "the merchant's real margin, not a policy constant."
        ),
    )
    product_role: ProductRole = Field(
        ...,
        description="anchor (drives the purchase) or companion (the attach item).",
    )
    mrp_inr: int = Field(
        default=0,
        ge=0,
        description="Maximum Retail Price (list price). 0 => same as price.",
    )
    stock_qty: int = Field(..., ge=0, description="Units currently in stock.")
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cost_not_above_price(self) -> "Product":
        if self.cost_price_inr > self.price_inr:
            raise ValueError(
                f"cost_price_inr ({self.cost_price_inr}) exceeds price_inr "
                f"({self.price_inr}) for '{self.product_id}'."
            )
        return self

    @property
    def margin_pct(self) -> float:
        """Natural retail margin: (price - cost) / price * 100."""
        if self.price_inr <= 0:
            return 0.0
        return (self.price_inr - self.cost_price_inr) / self.price_inr * 100

    @property
    def effective_mrp(self) -> int:
        """MRP to display; never below the selling price."""
        return self.mrp_inr if self.mrp_inr > self.price_inr else self.price_inr

    @property
    def discount_pct(self) -> float:
        """Real retail discount off MRP (0 if no MRP)."""
        mrp = self.effective_mrp
        return round((mrp - self.price_inr) / mrp * 100, 1) if mrp > 0 else 0.0

    def embedding_text(self) -> str:
        """Concatenated text fed to the embedding model.

        Kept in the model so the matching engine and any audit replay use an
        identical representation.
        """
        return f"{self.name}. {self.description} Tags: {', '.join(self.tags)}."
