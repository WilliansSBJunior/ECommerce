from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ml_api
from .models import MLListing, MLListingSnapshot


def _upsert_listing(session: Session, item: dict) -> MLListing:
    ml_item_id = item["id"]
    listing = session.scalar(select(MLListing).where(MLListing.ml_item_id == ml_item_id))
    if listing is None:
        listing = MLListing(ml_item_id=ml_item_id, title=item.get("title", ""))
        session.add(listing)

    listing.title = item.get("title", listing.title)
    listing.category_id = item.get("category_id")
    listing.currency = item.get("currency_id")
    listing.permalink = item.get("permalink")

    seller = item.get("seller") or {}
    listing.seller_id = str(seller.get("id")) if seller.get("id") is not None else None
    listing.seller_nickname = seller.get("nickname")

    return listing


def collect_by_query(
    session: Session,
    query: str,
    max_results: int = 50,
    with_details: bool = True,
    source: str = "ml_api",
) -> list[MLListing]:
    """Busca anuncios pelo termo, cria/atualiza os registros de anuncio e
    grava um snapshot de preco (historico) para cada um."""
    items = ml_api.search_items(query, max_results=max_results)

    details_by_id: dict[str, dict] = {}
    if with_details:
        details_by_id = ml_api.get_items_details_bulk([item["id"] for item in items])

    listings: list[MLListing] = []
    for item in items:
        listing = _upsert_listing(session, item)
        session.flush()  # garante listing.id disponivel

        detail = details_by_id.get(item["id"])

        shipping = item.get("shipping") or {}
        snapshot = MLListingSnapshot(
            listing_id=listing.id,
            price=item.get("price"),
            available_quantity=item.get("available_quantity"),
            free_shipping=shipping.get("free_shipping"),
            condition=item.get("condition"),
            listing_type=item.get("listing_type_id"),
            sold_quantity=detail.get("sold_quantity") if detail else None,
            source=source,
        )
        session.add(snapshot)
        listings.append(listing)

    return listings
