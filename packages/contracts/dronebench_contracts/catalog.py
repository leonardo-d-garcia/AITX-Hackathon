"""Catalog snapshot and declared interfaces (architecture section 7, supply-chain MVP).

A tiny checked-in snapshot, 6-12 items. Each offer carries source URL, source timestamp, currency,
quantity basis, region, and known/unknown stock and lead time. Where no verified data exists the
entry is labelled synthetic and carries no implied real supplier offer.

``synthetic`` is not a formality. ``CatalogOffer`` refuses to hold a supplier name or product URL
unless the entry is marked verified, so a demo fixture cannot accidentally assert that a real
company sells a real part at a real price.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .claims import Claim

CatalogCategory = Literal["battery", "spar", "servo", "motor", "propeller", "esc"]

InterfaceKind = Literal[
    "mechanical_bore",      # a round bore or shaft, sized in metres
    "mechanical_bolt",      # a bolt pattern
    "electrical_dc",        # a DC power connection with voltage/current limits
    "signal_pwm",           # a PWM servo/ESC signal line
    "mass_envelope",        # a bounding envelope a replacement must fit inside
]


class DeclaredInterface(BaseModel):
    """A machine-checkable interface. ``compatible_with`` is computed only from these."""

    model_config = ConfigDict(extra="forbid")

    interface_id: str
    kind: InterfaceKind
    #: Numeric characteristics in canonical SI. Compatibility compares these, never names.
    dimensions_m: dict[str, float] = Field(default_factory=dict)
    voltage_v: tuple[float, float] | None = Field(
        default=None, description="Inclusive (min, max) operating voltage."
    )
    current_limit_a: float | None = Field(default=None, ge=0)
    polarity: Literal["male", "female", "either"] = "either"

    def fits(self, other: "DeclaredInterface", *, tol_m: float = 1e-4) -> tuple[bool, list[str]]:
        """Return ``(fits, reasons_it_does_not)``. Pure geometry and ratings, no name matching."""
        reasons: list[str] = []
        if self.kind != other.kind:
            return False, [f"interface kinds differ: {self.kind} vs {other.kind}"]

        if self.polarity != "either" and other.polarity != "either":
            if self.polarity == other.polarity:
                reasons.append(f"both sides are {self.polarity}")

        for name, mine in self.dimensions_m.items():
            theirs = other.dimensions_m.get(name)
            if theirs is None:
                reasons.append(f"{name} is not declared on the counterpart")
                continue
            if name.endswith("_max"):
                if mine + tol_m < theirs:
                    reasons.append(f"{name}: {theirs:.4f} m exceeds the {mine:.4f} m limit")
            elif name.endswith("_min"):
                if theirs + tol_m < mine:
                    reasons.append(f"{name}: {theirs:.4f} m is below the {mine:.4f} m minimum")
            elif abs(mine - theirs) > tol_m:
                reasons.append(f"{name}: {theirs:.4f} m does not match {mine:.4f} m")

        if self.voltage_v and other.voltage_v:
            lo = max(self.voltage_v[0], other.voltage_v[0])
            hi = min(self.voltage_v[1], other.voltage_v[1])
            if lo > hi:
                reasons.append("operating voltage ranges do not overlap")

        if self.current_limit_a is not None and other.current_limit_a is not None:
            if other.current_limit_a + 1e-9 < self.current_limit_a:
                reasons.append(
                    f"current limit {other.current_limit_a:.1f} A is below the required "
                    f"{self.current_limit_a:.1f} A"
                )

        return (not reasons), reasons


class CatalogOffer(BaseModel):
    """A purchasable offer. Synthetic entries may not name a supplier or link a product."""

    model_config = ConfigDict(extra="forbid")

    supplier_name: str | None = None
    product_url: str | None = None
    source_url: str | None = Field(
        default=None, description="Where the figures were read, for a verified entry."
    )
    source_timestamp: datetime | None = None
    currency: Literal["USD", "EUR", "GBP"] | None = None
    unit_price: float | None = Field(default=None, ge=0)
    quantity_basis: Literal["each", "pair", "pack_of_4", "per_metre"] | None = None
    region: str | None = None
    stock_known: bool = False
    stock_units: int | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0)
    synthetic: bool = Field(
        default=True,
        description="A clearly labelled demo entry with no implied real supplier offer.",
    )

    @model_validator(mode="after")
    def _synthetic_names_nobody(self) -> Self:
        if self.synthetic:
            if self.supplier_name or self.product_url or self.source_url:
                raise ValueError(
                    "a synthetic offer must not name a supplier or link a product; that would "
                    "fabricate availability"
                )
        else:
            if not self.source_url or not self.source_timestamp:
                raise ValueError("a verified offer needs a source URL and a source timestamp")
        if self.stock_known and self.stock_units is None:
            raise ValueError("stock_known=True requires a stock figure")
        if not self.stock_known and self.stock_units is not None:
            raise ValueError("a stock figure contradicts stock_known=False")
        return self


class CatalogItem(BaseModel):
    """One catalog part: its claims, its declared interfaces, and its offers."""

    model_config = ConfigDict(extra="forbid")

    catalog_item_id: str
    category: CatalogCategory
    display_name: str
    mass_kg: Claim
    claims: dict[str, Claim] = Field(default_factory=dict)
    interfaces: list[DeclaredInterface] = Field(default_factory=list)
    offers: list[CatalogOffer] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    def interface_of(self, kind: InterfaceKind) -> DeclaredInterface | None:
        for interface in self.interfaces:
            if interface.kind == kind:
                return interface
        return None


class CatalogSnapshot(BaseModel):
    """The frozen, checked-in catalog. Live supplier search is optional and never required."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    snapshot_id: str
    captured_at: datetime
    items: list[CatalogItem]
    all_synthetic: bool = Field(
        default=True, description="True when every offer in the snapshot is a demo entry."
    )

    @model_validator(mode="after")
    def _size_and_labelling(self) -> Self:
        if not 6 <= len(self.items) <= 12:
            raise ValueError(
                f"the section 7 snapshot is roughly 6-12 items; got {len(self.items)}"
            )
        ids = [item.catalog_item_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate catalog_item_id")
        really_all_synthetic = all(
            offer.synthetic for item in self.items for offer in item.offers
        )
        if self.all_synthetic != really_all_synthetic:
            raise ValueError("all_synthetic does not match the offers it describes")
        return self

    def item(self, catalog_item_id: str) -> CatalogItem:
        for item in self.items:
            if item.catalog_item_id == catalog_item_id:
                return item
        raise KeyError(catalog_item_id)

    def of_category(self, category: CatalogCategory) -> list[CatalogItem]:
        return [item for item in self.items if item.category == category]
