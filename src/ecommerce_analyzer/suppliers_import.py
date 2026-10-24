"""Importa a tabela de fornecedores (xlsx, xls ou csv).

Os nomes de coluna variam muito de fornecedor para fornecedor, entao o
importador reconhece sinonimos (sem acento, minusculo). Exemplo de cabecalho
aceito:  Fornecedor | Produto | SKU | Custo | Frete | MOQ | Link | Palavras-chave

Colunas nao reconhecidas vao para `notes` do produto (nada se perde).
Reimportar a mesma planilha atualiza os produtos (chave: fornecedor + SKU,
ou fornecedor + nome quando nao ha SKU), em vez de duplicar.
"""

import re
import unicodedata

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Supplier, SupplierProduct

SYNONYMS: dict[str, list[str]] = {
    "supplier": ["fornecedor", "supplier", "vendor", "fabricante", "distribuidor", "loja"],
    "name": ["produto", "nome", "nome do produto", "descricao", "descricao do produto", "item", "product", "name", "titulo"],
    "sku": ["sku", "codigo", "cod", "ref", "referencia", "ean", "codigo do produto"],
    "cost_price": ["custo", "preco", "preco de custo", "valor", "valor unitario", "preco unitario", "custo unitario", "cost", "price", "preco fornecedor", "preco atacado"],
    "shipping_cost": ["frete", "frete unitario", "custo frete", "shipping", "frete por unidade"],
    "moq": ["moq", "minimo", "pedido minimo", "qtd minima", "quantidade minima", "min"],
    "url": ["url", "link", "site", "pagina"],
    "search_terms": ["termos", "termos de busca", "palavras chave", "palavra chave", "keywords", "busca"],
    "weight_grams": ["peso", "peso g", "peso (g)", "peso gramas", "weight"],
    "packaging_cost": ["embalagem", "custo embalagem", "packaging"],
    "tax_rate": ["imposto", "aliquota", "tax"],
    "category_hint": ["categoria", "category", "nicho"],
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"[_\-/]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def detect_columns(columns: list[str], manual_map: dict[str, str] | None = None) -> dict[str, str]:
    """Retorna {campo_interno: coluna_da_planilha}."""
    mapping: dict[str, str] = {}
    normed = {_norm(c): c for c in columns}
    for field, options in SYNONYMS.items():
        for opt in options:  # primeiro, igualdade exata
            if opt in normed and normed[opt] not in mapping.values():
                mapping[field] = normed[opt]
                break
    for field, options in SYNONYMS.items():  # depois, "contem" (ex: "Custo R$")
        if field in mapping:
            continue
        for ncol, col in normed.items():
            if col in mapping.values():
                continue
            if any(re.search(rf"\b{re.escape(opt)}\b", ncol) for opt in options if len(opt) > 2):
                mapping[field] = col
                break
    for field, col in (manual_map or {}).items():
        mapping[field] = col
    return mapping


def parse_money(value) -> float | None:
    """'R$ 1.234,56' -> 1234.56 ; '12.5' -> 12.5 ; 12 -> 12.0"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d,.\-]", "", str(value))
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_rate(value) -> float | None:
    """'6%' -> 0.06 ; 6 -> 0.06 ; 0.06 -> 0.06"""
    num = parse_money(value)
    if num is None:
        return None
    return num / 100 if num > 1 else num


def read_table(file_path: str, sheet: str | None = None) -> pd.DataFrame:
    lower = file_path.lower()
    if lower.endswith((".xlsx", ".xlsm", ".xls")):
        df = pd.read_excel(file_path, sheet_name=sheet or 0)
    else:
        df = pd.read_csv(file_path, sep=None, engine="python", encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    return df.dropna(how="all")


def import_suppliers(
    session: Session,
    file_path: str,
    sheet: str | None = None,
    default_supplier: str | None = None,
    manual_map: dict[str, str] | None = None,
) -> dict:
    df = read_table(file_path, sheet)
    mapping = detect_columns(list(df.columns), manual_map)
    if "name" not in mapping:
        raise ValueError(
            f"Nao achei a coluna com o nome do produto. Colunas: {list(df.columns)}. "
            "Use --map name=<coluna>."
        )
    if "cost_price" not in mapping:
        raise ValueError(
            f"Nao achei a coluna de custo. Colunas: {list(df.columns)}. Use --map cost_price=<coluna>."
        )
    used_cols = set(mapping.values())
    suppliers: dict[str, Supplier] = {}
    created = updated = skipped = 0
    warnings: list[str] = []

    for idx, row in df.iterrows():
        name = row.get(mapping["name"])
        if name is None or pd.isna(name) or not str(name).strip():
            skipped += 1
            continue
        name = str(name).strip()
        sup_name = default_supplier or "Fornecedor padrao"
        if "supplier" in mapping and pd.notna(row.get(mapping["supplier"])):
            sup_name = str(row[mapping["supplier"]]).strip()
        supplier = suppliers.get(sup_name) or session.scalar(select(Supplier).where(Supplier.name == sup_name))
        if supplier is None:
            supplier = Supplier(name=sup_name)
            session.add(supplier)
            session.flush()
        suppliers[sup_name] = supplier

        def val(field):
            col = mapping.get(field)
            if not col:
                return None
            v = row.get(col)
            return None if (v is None or (not isinstance(v, str) and pd.isna(v))) else v

        sku = str(val("sku")).strip() if val("sku") is not None else None
        if sku and sku.endswith(".0"):
            sku = sku[:-2]
        query = select(SupplierProduct).where(SupplierProduct.supplier_id == supplier.id)
        query = query.where(SupplierProduct.sku == sku) if sku else query.where(SupplierProduct.name == name)
        product = session.scalar(query)
        if product is None:
            product = SupplierProduct(supplier_id=supplier.id, name=name)
            session.add(product)
            created += 1
        else:
            updated += 1

        product.name = name
        product.sku = sku
        product.cost_price = parse_money(val("cost_price"))
        if product.cost_price is None:
            warnings.append(f"linha {idx + 2}: '{name}' sem custo valido")
        product.shipping_cost = parse_money(val("shipping_cost"))
        moq = parse_money(val("moq"))
        product.moq = int(moq) if moq is not None else None
        product.url = str(val("url")) if val("url") is not None else None
        product.search_terms = str(val("search_terms")) if val("search_terms") is not None else None
        product.weight_grams = parse_money(val("weight_grams"))
        product.packaging_cost = parse_money(val("packaging_cost"))
        product.tax_rate = parse_rate(val("tax_rate"))
        product.category_hint = str(val("category_hint")) if val("category_hint") is not None else None
        extras = {c: row[c] for c in df.columns if c not in used_cols and pd.notna(row[c])}
        product.notes = "; ".join(f"{k}: {v}" for k, v in extras.items()) or None
        session.flush()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "suppliers": len(suppliers),
        "mapping": mapping,
        "warnings": warnings,
    }
