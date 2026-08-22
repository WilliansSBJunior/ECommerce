from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Supplier(Base):
    """Fornecedor onde os produtos candidatos sao comprados."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    products: Mapped[list["SupplierProduct"]] = relationship(back_populates="supplier")


class SupplierProduct(Base):
    """Produto candidato oferecido por um fornecedor (custo de aquisicao)."""

    __tablename__ = "supplier_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(100))
    cost_price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="BRL")
    moq: Mapped[int | None] = mapped_column(Integer)
    shipping_cost: Mapped[float | None] = mapped_column(Float)
    url: Mapped[str | None] = mapped_column(String(1000))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    supplier: Mapped["Supplier"] = relationship(back_populates="products")
    watches: Mapped[list["ProductWatch"]] = relationship(back_populates="supplier_product")


class MLListing(Base):
    """Um anuncio do Mercado Livre (concorrente) que estamos acompanhando."""

    __tablename__ = "ml_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ml_item_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category_id: Mapped[str | None] = mapped_column(String(50))
    category_name: Mapped[str | None] = mapped_column(String(255))
    seller_id: Mapped[str | None] = mapped_column(String(50))
    seller_nickname: Mapped[str | None] = mapped_column(String(255))
    permalink: Mapped[str | None] = mapped_column(String(1000))
    currency: Mapped[str | None] = mapped_column(String(10))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    snapshots: Mapped[list["MLListingSnapshot"]] = relationship(
        back_populates="listing", order_by="MLListingSnapshot.captured_at"
    )
    watches: Mapped[list["ProductWatch"]] = relationship(back_populates="ml_listing")


class MLListingSnapshot(Base):
    """Foto de um anuncio em um momento no tempo -> constroi o historico de precos."""

    __tablename__ = "ml_listing_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("ml_listings.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    price: Mapped[float | None] = mapped_column(Float)
    sold_quantity: Mapped[int | None] = mapped_column(Integer)
    available_quantity: Mapped[int | None] = mapped_column(Integer)
    free_shipping: Mapped[bool | None] = mapped_column(Boolean)
    condition: Mapped[str | None] = mapped_column(String(50))
    listing_type: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(50), default="ml_api")
    # Campos extras que variam por ferramenta (ex: ferramentas pagas tipo Avante Pro):
    # vendas nos ultimos 30 dias, posicao no anuncio patrocinado, tendencia, etc.
    extra_data: Mapped[dict | None] = mapped_column(JSON)

    listing: Mapped["MLListing"] = relationship(back_populates="snapshots")


class ProductWatch(Base):
    """Liga um produto candidato do fornecedor a um ou mais anuncios concorrentes no ML."""

    __tablename__ = "product_watches"
    __table_args__ = (
        UniqueConstraint("supplier_product_id", "ml_listing_id", name="uq_product_watch"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_product_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_products.id"), nullable=False
    )
    ml_listing_id: Mapped[int] = mapped_column(ForeignKey("ml_listings.id"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    supplier_product: Mapped["SupplierProduct"] = relationship(back_populates="watches")
    ml_listing: Mapped["MLListing"] = relationship(back_populates="watches")
