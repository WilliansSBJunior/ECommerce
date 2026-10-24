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


# Identificadores dos marketplaces suportados (coluna `marketplace`).
MARKETPLACE_ML = "ml"
MARKETPLACE_SHOPEE = "shopee"
MARKETPLACE_TIKTOK = "tiktok"
MARKETPLACES = (MARKETPLACE_ML, MARKETPLACE_SHOPEE, MARKETPLACE_TIKTOK)
MARKETPLACE_LABELS = {
    MARKETPLACE_ML: "Mercado Livre",
    MARKETPLACE_SHOPEE: "Shopee",
    MARKETPLACE_TIKTOK: "TikTok Shop",
}


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
    # Termos de busca usados para achar os concorrentes (separados por ";").
    # Se vazio, usa o proprio nome do produto.
    search_terms: Mapped[str | None] = mapped_column(Text)
    weight_grams: Mapped[float | None] = mapped_column(Float)
    packaging_cost: Mapped[float | None] = mapped_column(Float)
    # Imposto sobre a venda especifico deste produto (0.06 = 6%). None = padrao.
    tax_rate: Mapped[float | None] = mapped_column(Float)
    category_hint: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    supplier: Mapped["Supplier"] = relationship(back_populates="products")
    watches: Mapped[list["ProductWatch"]] = relationship(back_populates="supplier_product")

    def query_terms(self) -> list[str]:
        raw = self.search_terms or self.name or ""
        terms = [t.strip() for t in raw.split(";") if t.strip()]
        return terms or [self.name]


class MLListing(Base):
    """Um anuncio concorrente que estamos acompanhando.

    Apesar do nome historico (o projeto nasceu so com Mercado Livre), a tabela
    guarda anuncios de qualquer marketplace: a coluna `marketplace` diz de onde
    veio e `ml_item_id` guarda o id externo (MLB123... no ML, "shopee:<shop>_<item>"
    na Shopee, "tiktok:<product_id>" no TikTok Shop).
    """

    __tablename__ = "ml_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ml_item_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    marketplace: Mapped[str] = mapped_column(String(20), default=MARKETPLACE_ML, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category_id: Mapped[str | None] = mapped_column(String(50))
    category_name: Mapped[str | None] = mapped_column(String(255))
    catalog_product_id: Mapped[str | None] = mapped_column(String(50))
    seller_id: Mapped[str | None] = mapped_column(String(50))
    seller_nickname: Mapped[str | None] = mapped_column(String(255))
    permalink: Mapped[str | None] = mapped_column(String(1000))
    thumbnail: Mapped[str | None] = mapped_column(String(1000))
    currency: Mapped[str | None] = mapped_column(String(10))
    # Data em que o anuncio foi criado no marketplace (permite estimar vendas/dia).
    date_created: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    original_price: Mapped[float | None] = mapped_column(Float)
    sold_quantity: Mapped[int | None] = mapped_column(Integer)
    # Vendas nos ultimos 30 dias quando a fonte informa (Shopee "sold", ferramentas pagas).
    sold_30d: Mapped[int | None] = mapped_column(Integer)
    available_quantity: Mapped[int | None] = mapped_column(Integer)
    free_shipping: Mapped[bool | None] = mapped_column(Boolean)
    condition: Mapped[str | None] = mapped_column(String(50))
    listing_type: Mapped[str | None] = mapped_column(String(50))
    logistic_type: Mapped[str | None] = mapped_column(String(50))  # fulfillment, xd_drop_off, ...
    official_store: Mapped[bool | None] = mapped_column(Boolean)
    rating: Mapped[float | None] = mapped_column(Float)
    reviews_count: Mapped[int | None] = mapped_column(Integer)
    # Posicao do anuncio no resultado da busca e o termo pesquisado.
    position: Mapped[int | None] = mapped_column(Integer)
    search_query: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(50), default="ml_api")
    # Campos extras que variam por fonte (ex: ferramentas pagas tipo Avante Pro):
    # vendas nos ultimos 30 dias, posicao no anuncio patrocinado, tendencia, etc.
    extra_data: Mapped[dict | None] = mapped_column(JSON)

    listing: Mapped["MLListing"] = relationship(back_populates="snapshots")


class ProductWatch(Base):
    """Liga um produto candidato do fornecedor a um ou mais anuncios concorrentes."""

    __tablename__ = "product_watches"
    __table_args__ = (
        UniqueConstraint("supplier_product_id", "ml_listing_id", name="uq_product_watch"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_product_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_products.id"), nullable=False
    )
    ml_listing_id: Mapped[int] = mapped_column(ForeignKey("ml_listings.id"), nullable=False)
    # Confianca do vinculo automatico (0-1). None = vinculo manual.
    match_score: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    supplier_product: Mapped["SupplierProduct"] = relationship(back_populates="watches")
    ml_listing: Mapped["MLListing"] = relationship(back_populates="watches")
