"""Importa dados de anuncios exportados de ferramentas pagas (ex: Avante Pro).

O CSV precisa ter pelo menos uma coluna de identificacao do anuncio:
'ml_item_id' (ex: MLB123456789) ou 'permalink' (URL do anuncio).

Colunas conhecidas sao mapeadas para campos do banco; qualquer outra coluna
do CSV e guardada em `extra_data` do snapshot, sem perder informacao.
"""

import re

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MLListing, MLListingSnapshot

KNOWN_COLUMNS = {
    "ml_item_id",
    "permalink",
    "title",
    "price",
    "sold_quantity",
    "available_quantity",
    "free_shipping",
    "condition",
    "listing_type",
    "category_name",
    "seller_nickname",
}

ITEM_ID_RE = re.compile(r"(MLB\d+)")


def _extract_item_id(row: pd.Series) -> str | None:
    if "ml_item_id" in row and pd.notna(row["ml_item_id"]):
        return str(row["ml_item_id"]).strip()
    if "permalink" in row and pd.notna(row["permalink"]):
        match = ITEM_ID_RE.search(str(row["permalink"]))
        if match:
            return match.group(1)
    return None


def import_csv(session: Session, file_path: str, source: str) -> dict:
    df = pd.read_csv(file_path)
    df.columns = [c.strip() for c in df.columns]

    imported, skipped = 0, 0
    for _, row in df.iterrows():
        item_id = _extract_item_id(row)
        if not item_id:
            skipped += 1
            continue

        listing = session.scalar(select(MLListing).where(MLListing.ml_item_id == item_id))
        if listing is None:
            listing = MLListing(ml_item_id=item_id, title=str(row.get("title") or item_id))
            session.add(listing)
            session.flush()
        else:
            if "title" in row and pd.notna(row["title"]):
                listing.title = str(row["title"])

        if "permalink" in row and pd.notna(row["permalink"]):
            listing.permalink = str(row["permalink"])
        if "category_name" in row and pd.notna(row["category_name"]):
            listing.category_name = str(row["category_name"])
        if "seller_nickname" in row and pd.notna(row["seller_nickname"]):
            listing.seller_nickname = str(row["seller_nickname"])

        extra_data = {
            col: row[col]
            for col in df.columns
            if col not in KNOWN_COLUMNS and pd.notna(row[col])
        }
        # JSON nao aceita tipos numpy diretamente; normaliza para tipos nativos do Python.
        extra_data = {k: (v.item() if hasattr(v, "item") else v) for k, v in extra_data.items()}

        snapshot = MLListingSnapshot(
            listing_id=listing.id,
            price=row.get("price") if pd.notna(row.get("price")) else None,
            sold_quantity=row.get("sold_quantity") if pd.notna(row.get("sold_quantity")) else None,
            available_quantity=(
                row.get("available_quantity") if pd.notna(row.get("available_quantity")) else None
            ),
            free_shipping=row.get("free_shipping") if pd.notna(row.get("free_shipping")) else None,
            condition=row.get("condition") if pd.notna(row.get("condition")) else None,
            listing_type=row.get("listing_type") if pd.notna(row.get("listing_type")) else None,
            source=source,
            extra_data=extra_data or None,
        )
        session.add(snapshot)
        imported += 1

    return {"imported": imported, "skipped": skipped}
