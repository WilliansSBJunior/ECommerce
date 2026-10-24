"""Grava anuncios e snapshots no banco, vindos da API do ML ou do extrator."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ml_api
from .models import MARKETPLACE_ML, MLListing, MLListingSnapshot, ProductWatch


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def upsert_listing(session: Session, data: dict) -> MLListing:
    """Cria/atualiza um anuncio a partir de um dicionario normalizado.

    Chaves aceitas: id (obrigatorio), marketplace, title, category_id,
    category_name, catalog_product_id, seller_id, seller_nickname, permalink,
    thumbnail, currency, date_created.
    """
    external_id = str(data["id"])
    listing = session.scalar(select(MLListing).where(MLListing.ml_item_id == external_id))
    if listing is None:
        listing = MLListing(
            ml_item_id=external_id,
            title=data.get("title") or external_id,
            marketplace=data.get("marketplace") or MARKETPLACE_ML,
        )
        session.add(listing)
    for key in (
        "title", "category_id", "category_name", "catalog_product_id", "seller_id",
        "seller_nickname", "permalink", "thumbnail", "currency",
    ):
        if data.get(key) not in (None, ""):
            setattr(listing, key, str(data[key]) if key != "title" else data[key])
    if data.get("date_created"):
        listing.date_created = _parse_dt(data["date_created"])
    session.flush()
    return listing


def add_snapshot(session: Session, listing: MLListing, data: dict, source: str) -> MLListingSnapshot:
    fields = (
        "price", "original_price", "sold_quantity", "sold_30d", "available_quantity",
        "free_shipping", "condition", "listing_type", "logistic_type", "official_store",
        "rating", "reviews_count", "position", "search_query", "extra_data",
    )
    snap = MLListingSnapshot(listing_id=listing.id, source=source, **{k: data.get(k) for k in fields})
    session.add(snap)
    return snap


def link(session: Session, supplier_product_id: int, listing: MLListing, match_score: float | None = None) -> bool:
    """Vincula produto do fornecedor ao anuncio (idempotente). True se criou."""
    exists = session.scalar(
        select(ProductWatch).where(
            ProductWatch.supplier_product_id == supplier_product_id,
            ProductWatch.ml_listing_id == listing.id,
        )
    )
    if exists:
        return False
    session.add(ProductWatch(supplier_product_id=supplier_product_id, ml_listing_id=listing.id, match_score=match_score))
    session.flush()
    return True


def _normalize_ml_item(item: dict, detail: dict | None, query: str | None) -> tuple[dict, dict]:
    seller = item.get("seller") or {}
    shipping = (detail or {}).get("shipping") or item.get("shipping") or {}
    listing_data = {
        "id": item["id"],
        "marketplace": MARKETPLACE_ML,
        "title": item.get("title"),
        "category_id": item.get("category_id"),
        "catalog_product_id": item.get("catalog_product_id"),
        "seller_id": seller.get("id") or item.get("seller_id"),
        "seller_nickname": seller.get("nickname"),
        "permalink": item.get("permalink"),
        "thumbnail": item.get("thumbnail"),
        "currency": item.get("currency_id"),
        "date_created": (detail or {}).get("date_created"),
    }
    snap_data = {
        "price": item.get("price"),
        "original_price": item.get("original_price"),
        "available_quantity": (detail or {}).get("available_quantity", item.get("available_quantity")),
        "free_shipping": shipping.get("free_shipping"),
        "logistic_type": shipping.get("logistic_type"),
        "condition": item.get("condition"),
        "listing_type": item.get("listing_type_id"),
        "official_store": bool(item.get("official_store_id")),
        # sold_quantity: a API so devolve para o dono do anuncio desde 2025;
        # quando vier, usamos. Senao fica None e o score usa outras fontes.
        "sold_quantity": (detail or {}).get("sold_quantity", item.get("sold_quantity")),
        "position": item.get("_position"),
        "search_query": query,
    }
    return listing_data, snap_data


def collect_by_query(
    session: Session,
    query: str,
    max_results: int = 50,
    with_details: bool = True,
    source: str = "ml_api",
    supplier_product_id: int | None = None,
    category: str | None = None,
) -> list[MLListing]:
    """Busca anuncios pelo termo, cria/atualiza os registros e grava um snapshot
    para cada um. Com supplier_product_id, ja vincula ao produto do fornecedor."""
    items = ml_api.search_items(query, max_results=max_results, category=category)
    details = ml_api.get_items_details_bulk([i["id"] for i in items]) if with_details else {}
    listings: list[MLListing] = []
    for item in items:
        listing_data, snap_data = _normalize_ml_item(item, details.get(item["id"]), query)
        listing = upsert_listing(session, listing_data)
        add_snapshot(session, listing, snap_data, source)
        if supplier_product_id:
            link(session, supplier_product_id, listing)
        listings.append(listing)
    return listings


def collect_best_sellers(session: Session, category_id: str, source: str = "ml_highlights") -> list[MLListing]:
    """Grava os mais vendidos da categoria. Itens do tipo PRODUCT (catalogo) sao
    expandidos para o anuncio vencedor do catalogo."""
    highlights = ml_api.get_category_highlights(category_id)
    item_ids: list[tuple[str, int]] = []
    for h in highlights:
        if h.get("type") == "ITEM":
            item_ids.append((h["id"], h.get("position")))
        elif h.get("type") in ("PRODUCT", "USER_PRODUCT"):
            try:
                winners = ml_api.get_product_items(h["id"])
            except ml_api.MLAuthError:
                winners = []
            if winners:
                item_ids.append((winners[0].get("item_id") or winners[0].get("id"), h.get("position")))
    details = ml_api.get_items_details_bulk([i for i, _ in item_ids if i])
    listings = []
    for item_id, position in item_ids:
        detail = details.get(item_id)
        if not detail:
            continue
        detail["_position"] = position
        listing_data, snap_data = _normalize_ml_item(detail, detail, None)
        snap_data["extra_data"] = {"best_seller_category": category_id, "best_seller_position": position}
        listing = upsert_listing(session, listing_data)
        add_snapshot(session, listing, snap_data, source)
        listings.append(listing)
    return listings
