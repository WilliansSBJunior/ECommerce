"""Garimpo reverso: dos mais vendidos do marketplace para o catalogo do fornecedor.

Fluxo normal do projeto: tabela do fornecedor -> busca concorrentes -> score.
Aqui e o contrario:
 1. descobre os MAIS VENDIDOS de uma categoria (ML pela API ou pela pagina
    publica de mais vendidos; Shopee pela pagina da categoria ordenada por
    vendas, no navegador logado);
 2. grava os anuncios com snapshot de fonte "mais_vendidos_ml" /
    "mais_vendidos_shopee" e extra_data {"categoria", "rank"};
 3. procura cada anuncio no catalogo ja importado do fornecedor (similaridade
    do matcher) e, se o fornecedor tiver `search_url`, na busca do site dele;
 4. `list_opportunities` monta a lista com status encontrado/nao encontrado,
    custo no fornecedor e lucro por unidade vendendo no preco do anuncio.

Nunca inventa dado: o que nao foi encontrado fica como "nao_encontrado".
"""

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import collector, ml_api, supplier_search
from .config import DEFAULT_PACKAGING_COST, DEFAULT_TAX_RATE
from .fees import marketplace_fee
from .matcher import similarity
from .models import (
    MARKETPLACE_ML,
    MARKETPLACE_SHOPEE,
    MLListing,
    MLListingSnapshot,
    ProductWatch,
    Supplier,
    SupplierProduct,
)

SOURCE_PREFIX = "mais_vendidos_"
SOURCES = {MARKETPLACE_ML: "mais_vendidos_ml", MARKETPLACE_SHOPEE: "mais_vendidos_shopee"}
STATUS_FOUND = "encontrado"
STATUS_MISSING = "nao_encontrado"


def category_from_url(url: str | None) -> str | None:
    """Extrai o id da categoria de uma URL de mais vendidos do ML ou de categoria da Shopee."""
    if not url:
        return None
    m = re.search(r"\b(MLB\d+)\b", url) or re.search(r"[-.]cat\.(?:\d+\.)*(\d+)", url) or re.search(r"[?&]catid=(\d+)", url)
    return m.group(1) if m else None


def discovery_url(marketplace: str, category: str) -> str:
    from .scraper import ML_BEST_SELLERS_URL, SHOPEE_CATEGORY_URL

    if marketplace == MARKETPLACE_ML:
        return ML_BEST_SELLERS_URL.format(categoria=category)
    if marketplace == MARKETPLACE_SHOPEE:
        return SHOPEE_CATEGORY_URL.format(catid=category)
    raise ValueError(f"Garimpo reverso nao suporta o marketplace {marketplace}")


# --------------------------------------------------------------- descoberta
def store_discovered(
    session: Session,
    products: list[dict],
    marketplace: str,
    category_id: str | None = None,
    category_name: str | None = None,
    extra: dict | None = None,
) -> list[MLListing]:
    """Grava a saida do extrator como mais vendidos (rank = ordem na pagina)."""
    from .scraper import LISTING_KEYS

    listings = []
    for idx, p in enumerate(products, 1):
        p = dict(p)
        rank = p.pop("rank", None) or p.get("position") or idx
        p["position"] = rank
        if not p.get("category_id") and category_id:
            p["category_id"] = category_id
        if category_name:
            p["category_name"] = category_name
        listing = collector.upsert_listing(session, {k: v for k, v in p.items() if k in LISTING_KEYS})
        snap = {k: v for k, v in p.items() if k not in LISTING_KEYS}
        extras = {"categoria": category_id or p.get("category_id"), "rank": rank}
        if snap.pop("sponsored", None):
            extras["patrocinado"] = True
        extras.update(extra or {})
        snap["extra_data"] = extras
        collector.add_snapshot(session, listing, snap, SOURCES[marketplace])
        listings.append(listing)
    session.flush()
    return listings


def discover_ml_api(session: Session, category_id: str, limit: int = 50) -> list[MLListing]:
    """Mais vendidos da categoria pela API oficial (exige token)."""
    name = None
    try:
        name = (ml_api.get_category(category_id) or {}).get("name")
    except Exception:  # nome e opcional; erro de token aparece na chamada principal
        name = None
    return collector.collect_best_sellers(
        session, category_id, source=SOURCES[MARKETPLACE_ML], limit=limit, category_name=name
    )


def discover_scrape(
    session: Session,
    marketplace: str,
    category: str | None = None,
    url: str | None = None,
    limit: int = 50,
    headless: bool = False,
    ctx=None,
    category_name: str | None = None,
) -> tuple[list[MLListing], str]:
    """Mais vendidos pelo navegador logado. ML: /mais-vendidos/{categoria};
    Shopee: pagina da categoria ordenada por vendas. `url` aceita qualquer
    pagina colada pelo usuario. Retorna (anuncios, caminho dos brutos)."""
    from . import scraper

    category = category or category_from_url(url)
    if not url:
        if not category:
            raise ValueError("Informe a categoria ou a URL")
        url = discovery_url(marketplace, category)
    parser = None
    if marketplace == MARKETPLACE_ML:
        parser = lambda html, _payloads: scraper.parse_ml_best_sellers(html, category)  # noqa: E731
    products, raw = scraper.scrape_url(
        marketplace, url, limit=limit, headless=headless, ctx=ctx, parser=parser,
        label=f"mais_vendidos_{category or 'url'}",
    )
    name = category_name or next((p.get("category_name") for p in products if p.get("category_name")), None)
    return store_discovered(session, products, marketplace, category, name), raw


# --------------------------------------------------------------- casamento
def _product_score(product: SupplierProduct, title: str) -> float:
    terms = product.query_terms() + [product.name]
    return max(similarity(t, title) for t in terms)


def match_catalog(
    session: Session,
    listing: MLListing,
    supplier_id: int | None = None,
    threshold: float = 0.6,
    products: list[SupplierProduct] | None = None,
) -> tuple[SupplierProduct, float] | None:
    """Procura o anuncio no catalogo ja importado e vincula (ProductWatch) todo
    produto com similaridade >= threshold. Retorna o melhor (produto, score)."""
    if products is None:
        q = select(SupplierProduct)
        if supplier_id:
            q = q.where(SupplierProduct.supplier_id == supplier_id)
        products = session.scalars(q).all()
    best = None
    for product in products:
        score = _product_score(product, listing.title)
        if score < threshold:
            continue
        collector.link(session, product.id, listing, match_score=score)
        if best is None or score > best[1]:
            best = (product, score)
    return best


def match_supplier_site(
    session: Session,
    supplier: Supplier,
    listing: MLListing,
    threshold: float = 0.6,
    ctx=None,
    use_browser: bool = True,
    headless: bool = False,
) -> tuple[SupplierProduct, float] | None:
    """Busca o titulo do anuncio no site do fornecedor; se o melhor resultado
    tiver similaridade >= threshold, cria/atualiza o SupplierProduct e vincula."""
    query = supplier_search.query_from_title(listing.title)
    if not query or not supplier.search_url:
        return None
    results = supplier_search.search_supplier(supplier, query, ctx=ctx, use_browser=use_browser, headless=headless)
    scored = [(similarity(query, r["title"]), r) for r in results if r.get("title")]
    scored = [x for x in scored if x[0] >= threshold]
    if not scored:
        return None
    score, best = max(scored, key=lambda x: (x[0], x[1].get("price") is not None))
    q = select(SupplierProduct).where(SupplierProduct.supplier_id == supplier.id)
    q = q.where(SupplierProduct.url == best["url"]) if best.get("url") else q.where(SupplierProduct.name == best["title"])
    product = session.scalar(q)
    if product is None:
        product = SupplierProduct(supplier_id=supplier.id, name=best["title"][:255])
        session.add(product)
    product.name = best["title"][:255]
    if best.get("price") is not None:
        product.cost_price = best["price"]
    product.url = best.get("url") or product.url
    product.sku = best.get("sku") or product.sku
    product.search_terms = query
    note = f"encontrado na busca do site em {datetime.now():%d/%m/%Y}"
    if best.get("price") is None:
        note += " (sem preco na pagina - talvez precise de supplier-login)"
    product.notes = note
    session.flush()
    collector.link(session, product.id, listing, match_score=score)
    return product, score


def reverse_match(
    session: Session,
    listings: list[MLListing],
    supplier_id: int | None = None,
    threshold: float = 0.6,
    site_search: bool = True,
    ctx=None,
    use_browser: bool = True,
    headless: bool = False,
) -> list[dict]:
    """Casa cada anuncio mais vendido com o catalogo e, se preciso, com o site
    do fornecedor (so com supplier_id e search_url cadastrada). Uma linha por anuncio."""
    supplier = session.get(Supplier, supplier_id) if supplier_id else None
    q = select(SupplierProduct)
    if supplier_id:
        q = q.where(SupplierProduct.supplier_id == supplier_id)
    products = session.scalars(q).all()
    rows = []
    for listing in listings:
        found = match_catalog(session, listing, supplier_id, threshold, products=products)
        origin = "catalogo" if found else None
        if found is None and site_search and supplier is not None and supplier.search_url:
            try:
                found = match_supplier_site(session, supplier, listing, threshold, ctx=ctx, use_browser=use_browser, headless=headless)
            except Exception as exc:  # erro de rede/site: reporta literal e segue
                rows.append(_row(listing, None, None, erro=f"{type(exc).__name__}: {exc}"))
                continue
            if found:
                origin = "site"
                if found[0] not in products:
                    products.append(found[0])
        rows.append(_row(listing, found, origin))
    return rows


def _row(listing: MLListing, found, origin, erro: str | None = None) -> dict:
    snap = _latest_discovery_snapshot(listing) or (listing.snapshots[-1] if listing.snapshots else None)
    product, score = found if found else (None, None)
    return {
        "ml_item_id": listing.ml_item_id,
        "rank": (snap.extra_data or {}).get("rank") if snap else None,
        "title": listing.title,
        "price": snap.price if snap else None,
        "sold_quantity": snap.sold_quantity if snap else None,
        "sold_30d": snap.sold_30d if snap else None,
        "status": STATUS_FOUND if product else STATUS_MISSING,
        "supplier_name": product.supplier.name if product and product.supplier else None,
        "product_name": product.name if product else None,
        "cost_price": product.cost_price if product else None,
        "match_score": score,
        "origin": origin,
        "error": erro,
    }


# --------------------------------------------------------------- oportunidades
def _latest_discovery_snapshot(listing: MLListing) -> MLListingSnapshot | None:
    snaps = [s for s in listing.snapshots if (s.source or "").startswith(SOURCE_PREFIX)]
    return snaps[-1] if snaps else None


def _unit_profit(marketplace: str, price: float | None, product: SupplierProduct | None,
                 logistic: str | None, plan: str | None) -> dict:
    out = {"fee_total": None, "tax_amount": None, "unit_costs": None, "unit_profit": None, "margin": None}
    if not price or product is None or product.cost_price is None:
        return out
    tax = product.tax_rate if product.tax_rate is not None else DEFAULT_TAX_RATE
    packaging = product.packaging_cost if product.packaging_cost is not None else DEFAULT_PACKAGING_COST
    unit_costs = float(product.cost_price) + float(product.shipping_cost or 0) + float(packaging)
    fee = marketplace_fee(marketplace, price, plan=plan, logistic=logistic)
    tax_amount = round(price * tax, 2)
    profit = round(price - fee.total - tax_amount - unit_costs, 2)
    out.update(fee_total=fee.total, tax_amount=tax_amount, unit_costs=round(unit_costs, 2),
               unit_profit=profit, margin=round(profit / price, 4))
    return out


def list_opportunities(
    session: Session,
    marketplace: str | None = None,
    category: str | None = None,
    only_missing: bool = False,
    plan_by_marketplace: dict | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Anuncios com snapshot "mais_vendidos_*", com status no fornecedor e lucro.

    Lucro/un = preco do anuncio - taxa do marketplace - imposto (do produto ou
    DEFAULT_TAX_RATE) - custo - frete do fornecedor - embalagem (do produto ou
    DEFAULT_PACKAGING_COST). O fornecedor e o do vinculo com maior match_score
    (vinculo manual, sem score, conta como 1)."""
    from .scoring import estimate_sales_per_day

    plan_by_marketplace = plan_by_marketplace or {}
    now = now or datetime.now(timezone.utc)
    q = (
        select(MLListing)
        .join(MLListingSnapshot, MLListingSnapshot.listing_id == MLListing.id)
        .where(MLListingSnapshot.source.like(SOURCE_PREFIX.replace("_", "\\_") + "%", escape="\\"))
        .distinct()
    )
    if marketplace:
        q = q.where(MLListing.marketplace == marketplace)
    rows = []
    for listing in session.scalars(q).all():
        snap = _latest_discovery_snapshot(listing)
        extra = snap.extra_data or {}
        cat = str(extra.get("categoria") or listing.category_id or "") or None
        if category and cat != str(category):
            continue
        watches = sorted(listing.watches, key=lambda w: -(w.match_score if w.match_score is not None else 1.0))
        best: ProductWatch | None = watches[0] if watches else None
        if only_missing and best is not None:
            continue
        product = best.supplier_product if best else None
        mk = listing.marketplace or MARKETPLACE_ML
        spd, method = estimate_sales_per_day(listing, now)
        calc = _unit_profit(mk, snap.price, product, snap.logistic_type, plan_by_marketplace.get(mk))
        rows.append({
            "marketplace": mk,
            "category_id": cat,
            "category_name": listing.category_name,
            "rank": extra.get("rank") or snap.position,
            "ml_item_id": listing.ml_item_id,
            "title": listing.title,
            "permalink": listing.permalink,
            "price": snap.price,
            "sold_quantity": snap.sold_quantity,
            "sold_30d": snap.sold_30d,
            "sales_per_day": round(spd, 2) if spd is not None else None,
            "sales_method": method,
            "status": STATUS_FOUND if product else STATUS_MISSING,
            "found": product is not None,
            "supplier_name": product.supplier.name if product and product.supplier else None,
            "supplier_product_id": product.id if product else None,
            "product_name": product.name if product else None,
            "product_url": product.url if product else None,
            "match_score": (best.match_score if best.match_score is not None else 1.0) if best else None,
            "cost_price": product.cost_price if product else None,
            "n_suppliers": len({w.supplier_product.supplier_id for w in watches}),
            "captured_at": snap.captured_at.strftime("%d/%m/%Y %H:%M") if snap.captured_at else None,
            **calc,
        })
    rows.sort(key=lambda r: (r["marketplace"], r["category_id"] or "", r["rank"] if r["rank"] is not None else 10**6))
    return rows
