import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MLListing, MLListingSnapshot, ProductWatch, SupplierProduct


def _latest_snapshot_per_listing(session: Session) -> pd.DataFrame:
    listings = session.scalars(select(MLListing)).all()
    rows = []
    for listing in listings:
        if not listing.snapshots:
            continue
        latest = listing.snapshots[-1]
        rows.append(
            {
                "ml_item_id": listing.ml_item_id,
                "title": listing.title,
                "category_name": listing.category_name,
                "seller_nickname": listing.seller_nickname,
                "price": latest.price,
                "sold_quantity": latest.sold_quantity,
                "available_quantity": latest.available_quantity,
                "free_shipping": latest.free_shipping,
                "condition": latest.condition,
                "listing_type": latest.listing_type,
                "source": latest.source,
                "captured_at": latest.captured_at,
                "permalink": listing.permalink,
            }
        )
    return pd.DataFrame(rows)


def _price_history(session: Session) -> pd.DataFrame:
    snapshots = session.scalars(select(MLListingSnapshot)).all()
    rows = [
        {
            "ml_item_id": snap.listing.ml_item_id,
            "title": snap.listing.title,
            "captured_at": snap.captured_at,
            "price": snap.price,
            "sold_quantity": snap.sold_quantity,
            "available_quantity": snap.available_quantity,
            "source": snap.source,
            "extra_data": snap.extra_data,
        }
        for snap in snapshots
    ]
    return pd.DataFrame(rows)


def _supplier_products(session: Session) -> pd.DataFrame:
    products = session.scalars(select(SupplierProduct)).all()
    rows = [
        {
            "supplier": p.supplier.name if p.supplier else None,
            "product": p.name,
            "sku": p.sku,
            "cost_price": p.cost_price,
            "currency": p.currency,
            "moq": p.moq,
            "shipping_cost": p.shipping_cost,
            "url": p.url,
        }
        for p in products
    ]
    return pd.DataFrame(rows)


def _comparison(session: Session) -> pd.DataFrame:
    watches = session.scalars(select(ProductWatch)).all()
    rows = []
    for watch in watches:
        sp = watch.supplier_product
        listing = watch.ml_listing
        latest = listing.snapshots[-1] if listing.snapshots else None
        rows.append(
            {
                "produto_fornecedor": sp.name,
                "fornecedor": sp.supplier.name if sp.supplier else None,
                "custo_fornecedor": sp.cost_price,
                "frete_fornecedor": sp.shipping_cost,
                "anuncio_concorrente": listing.title,
                "ml_item_id": listing.ml_item_id,
                "preco_concorrente": latest.price if latest else None,
                "vendidos_concorrente": latest.sold_quantity if latest else None,
                "permalink": listing.permalink,
                "notas": watch.notes,
            }
        )
    return pd.DataFrame(rows)


def export_to_excel(session: Session, output_path: str) -> None:
    sheets = {
        "Anuncios (atual)": _latest_snapshot_per_listing(session),
        "Historico de Precos": _price_history(session),
        "Produtos Fornecedor": _supplier_products(session),
        "Comparativo": _comparison(session),
    }
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            if df.empty:
                df = pd.DataFrame({"info": ["sem dados ainda"]})
            # remove timezone (Excel nao aceita datas com tz)
            for col in df.select_dtypes(include=["datetimetz"]).columns:
                df[col] = df[col].dt.tz_localize(None)
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
