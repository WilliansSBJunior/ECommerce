"""Importa dados de anuncios exportados de ferramentas pagas (ex: Avante Pro).

O CSV precisa ter pelo menos uma coluna de identificacao do anuncio:
'ml_item_id' (ex: MLB123456789) ou 'permalink' (URL do anuncio).

Colunas conhecidas (e sinonimos comuns dessas ferramentas, ex:
'vendas_ultimos_30_dias', 'faturamento', 'data_criacao') sao mapeadas para
campos do banco; qualquer outra coluna e guardada em `extra_data` do snapshot.
"""

import re
import unicodedata

import pandas as pd
from sqlalchemy.orm import Session

from .collector import add_snapshot, upsert_listing
from .suppliers_import import parse_money

# campo interno -> sinonimos (normalizados: minusculo, sem acento, "_" vira espaco)
ALIASES = {
    "ml_item_id": ["ml item id", "item id", "id anuncio", "mlb", "codigo anuncio", "id"],
    "permalink": ["permalink", "link", "url", "link anuncio"],
    "title": ["title", "titulo", "nome", "anuncio"],
    "price": ["price", "preco", "preco atual", "valor"],
    "sold_quantity": ["sold quantity", "vendidos", "vendas totais", "total vendido", "unidades vendidas"],
    "sold_30d": ["vendas ultimos 30 dias", "vendas 30 dias", "vendas 30d", "vendas mes", "vendas mensais", "sold 30d"],
    "available_quantity": ["available quantity", "estoque", "disponivel"],
    "free_shipping": ["free shipping", "frete gratis"],
    "condition": ["condition", "condicao"],
    "listing_type": ["listing type", "tipo anuncio", "tipo de anuncio"],
    "logistic_type": ["logistic type", "logistica", "tipo de envio", "envio"],
    "category_name": ["category name", "categoria"],
    "seller_nickname": ["seller nickname", "vendedor", "loja", "seller"],
    "date_created": ["date created", "data criacao", "data de criacao", "criado em"],
    "rating": ["rating", "nota", "avaliacao"],
    "reviews_count": ["reviews count", "avaliacoes", "qtd avaliacoes", "opinioes"],
    "position": ["position", "posicao"],
    "marketplace": ["marketplace", "canal", "plataforma"],
}
ITEM_ID_RE = re.compile(r"(MLB)-?(\d{6,})")
LISTING_FIELDS = {"title", "category_name", "seller_nickname", "permalink", "date_created", "marketplace"}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[\s_\-/()]+", " ", text).strip()


def _map_columns(columns) -> dict[str, str]:
    normed = {_norm(c): c for c in columns}
    mapping = {}
    for field, opts in ALIASES.items():
        for opt in [field.replace("_", " ")] + opts:
            if opt in normed and normed[opt] not in mapping.values():
                mapping[field] = normed[opt]
                break
    return mapping


def _bool(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("true", "1", "sim", "s", "yes", "y", "verdadeiro")


def _extract_item_id(row: pd.Series, mapping: dict) -> str | None:
    for field in ("ml_item_id", "permalink"):
        col = mapping.get(field)
        if col and pd.notna(row.get(col)):
            m = ITEM_ID_RE.search(str(row[col]))
            if m:
                return f"{m.group(1)}{m.group(2)}"
            if field == "ml_item_id":
                return str(row[col]).strip()
    return None


def import_csv(session: Session, file_path: str, source: str) -> dict:
    df = pd.read_csv(file_path, sep=None, engine="python", encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    mapping = _map_columns(df.columns)
    used = set(mapping.values())

    imported, skipped = 0, 0
    for _, row in df.iterrows():
        item_id = _extract_item_id(row, mapping)
        if not item_id:
            skipped += 1
            continue

        def get(field):
            col = mapping.get(field)
            return row[col] if col and pd.notna(row.get(col)) else None

        listing_data = {"id": item_id}
        for f in LISTING_FIELDS:
            if get(f) is not None:
                listing_data[f] = str(get(f))
        listing = upsert_listing(session, listing_data)

        snap = {
            "price": parse_money(get("price")),
            "sold_quantity": int(parse_money(get("sold_quantity"))) if get("sold_quantity") is not None else None,
            "sold_30d": int(parse_money(get("sold_30d"))) if get("sold_30d") is not None else None,
            "available_quantity": int(parse_money(get("available_quantity"))) if get("available_quantity") is not None else None,
            "free_shipping": _bool(get("free_shipping")) if get("free_shipping") is not None else None,
            "condition": get("condition"),
            "listing_type": get("listing_type"),
            "logistic_type": get("logistic_type"),
            "rating": parse_money(get("rating")),
            "reviews_count": int(parse_money(get("reviews_count"))) if get("reviews_count") is not None else None,
            "position": int(parse_money(get("position"))) if get("position") is not None else None,
        }
        extra = {c: row[c] for c in df.columns if c not in used and pd.notna(row[c])}
        snap["extra_data"] = {k: (v.item() if hasattr(v, "item") else v) for k, v in extra.items()} or None
        add_snapshot(session, listing, snap, source)
        imported += 1

    return {"imported": imported, "skipped": skipped, "mapping": mapping}
