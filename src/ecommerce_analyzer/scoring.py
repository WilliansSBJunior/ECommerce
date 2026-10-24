"""Calculo de viabilidade: lucro, demanda, concorrencia e score de 0 a 100.

Entrada: um produto do fornecedor (custo) e os anuncios concorrentes
vinculados a ele em um marketplace (preco, vendidos, historico de snapshots).
Saida: um `ProductScore` com todos os indicadores usados no dashboard.

Como estimamos vendas por dia de cada anuncio (em ordem de preferencia):
 1. diferenca de `sold_quantity` entre o snapshot mais antigo e o mais novo,
    dividida pelos dias entre eles (precisa de >= 1 dia de historico);
 2. `sold_30d` informado pela fonte (Shopee mostra vendas mensais; ferramentas
    pagas exportam "vendas ultimos 30 dias") / 30;
 3. `sold_quantity` total / idade do anuncio em dias (`date_created`);
 4. sem dado -> None (o produto recebe a flag "poucos dados").
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from statistics import median

from .config import DEFAULT_PACKAGING_COST, DEFAULT_TAX_RATE
from .fees import breakeven_price, marketplace_fee
from .models import MLListing, MLListingSnapshot, SupplierProduct

# Pesos do score final (somam 1).
WEIGHTS = {"margin": 0.35, "demand": 0.30, "competition": 0.20, "unit_profit": 0.15}

# Limites usados para normalizar cada componente para 0-100.
MARGIN_FULL_SCORE = 0.40      # margem >= 40% -> 100 pontos
DEMAND_FULL_SCORE = 3000      # >= 3000 unidades/mes no mercado -> 100 pontos
UNIT_PROFIT_FULL_SCORE = 50.0  # >= R$50 de lucro/unidade -> 100 pontos
COMPETITION_FEW = 5           # <= 5 vendedores -> 100 pontos
COMPETITION_MANY = 60         # >= 60 vendedores -> 0 pontos


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _days_between(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return abs((b - a).total_seconds()) / 86400.0


def estimate_sales_per_day(listing: MLListing, now: datetime | None = None) -> tuple[float | None, str]:
    """Retorna (vendas/dia estimadas, metodo usado)."""
    now = now or datetime.now(timezone.utc)
    snaps: list[MLListingSnapshot] = [s for s in listing.snapshots if s.sold_quantity is not None]
    if len(snaps) >= 2:
        first, last = snaps[0], snaps[-1]
        days = _days_between(first.captured_at, last.captured_at)
        if days and days >= 1 and last.sold_quantity >= first.sold_quantity:
            return (last.sold_quantity - first.sold_quantity) / days, "historico"
    latest = listing.snapshots[-1] if listing.snapshots else None
    if latest is not None and latest.sold_30d is not None:
        return latest.sold_30d / 30.0, "sold_30d"
    if latest is not None and latest.sold_quantity is not None and listing.date_created is not None:
        age = _days_between(listing.date_created, now)
        if age and age >= 7:
            return latest.sold_quantity / age, "idade_anuncio"
    return None, "sem_dado"


@dataclass
class ListingStat:
    ml_item_id: str
    title: str
    seller: str | None
    price: float | None
    sold_quantity: int | None
    sales_per_day: float | None
    method: str
    permalink: str | None
    position: int | None
    logistic_type: str | None
    free_shipping: bool | None


@dataclass
class ProductScore:
    supplier_product_id: int
    product_name: str
    supplier_name: str | None
    sku: str | None
    marketplace: str
    cost_price: float
    shipping_in: float
    packaging_cost: float
    tax_rate: float
    unit_costs: float
    n_listings: int
    n_sellers: int
    price_min: float | None
    price_p25: float | None
    price_median: float | None
    price_max: float | None
    suggested_price: float | None
    fee_commission: float | None
    fee_fixed: float | None
    fee_total: float | None
    tax_amount: float | None
    unit_profit: float | None
    margin: float | None
    markup: float | None
    breakeven: float | None
    market_sales_per_day: float | None
    market_units_month: float | None
    market_revenue_month: float | None
    top_listing_share: float | None
    listings_with_sales_data: int
    expected_share: float | None
    expected_units_month: float | None
    expected_profit_month: float | None
    score_margin: float
    score_demand: float
    score_competition: float
    score_unit_profit: float
    score: float
    flags: list[str] = field(default_factory=list)
    listings: list[ListingStat] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        return data


def _percentile(values: list[float], pct: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    k = (len(values) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def score_product(
    product: SupplierProduct,
    listings: list[MLListing],
    marketplace: str,
    plan: str | None = None,
    price_strategy: str = "median",
    tax_rate: float | None = None,
    logistic: str | None = None,
    now: datetime | None = None,
) -> ProductScore:
    """Calcula os indicadores de um produto do fornecedor em um marketplace.

    price_strategy: "median" (vende no preco mediano do mercado), "p25"
    (entra mais barato que 75% dos concorrentes) ou "min" (bate o menor preco).
    """
    now = now or datetime.now(timezone.utc)
    tax = tax_rate if tax_rate is not None else (product.tax_rate if product.tax_rate is not None else DEFAULT_TAX_RATE)
    cost = float(product.cost_price or 0)
    shipping_in = float(product.shipping_cost or 0)
    packaging = float(product.packaging_cost if product.packaging_cost is not None else DEFAULT_PACKAGING_COST)
    unit_costs = cost + shipping_in + packaging

    stats: list[ListingStat] = []
    for listing in listings:
        latest = listing.snapshots[-1] if listing.snapshots else None
        if latest is None:
            continue
        spd, method = estimate_sales_per_day(listing, now)
        stats.append(
            ListingStat(
                ml_item_id=listing.ml_item_id,
                title=listing.title,
                seller=listing.seller_nickname,
                price=latest.price,
                sold_quantity=latest.sold_quantity,
                sales_per_day=spd,
                method=method,
                permalink=listing.permalink,
                position=latest.position,
                logistic_type=latest.logistic_type,
                free_shipping=latest.free_shipping,
            )
        )

    prices = [s.price for s in stats if s.price]
    sellers = {s.seller or s.ml_item_id for s in stats}
    flags: list[str] = []

    price_min = min(prices) if prices else None
    price_max = max(prices) if prices else None
    price_median = median(prices) if prices else None
    price_p25 = _percentile(prices, 0.25) if prices else None
    suggested = {"median": price_median, "p25": price_p25, "min": price_min}.get(price_strategy, price_median)

    fee = marketplace_fee(marketplace, suggested, plan=plan, logistic=logistic) if suggested else None
    tax_amount = round(suggested * tax, 2) if suggested else None
    unit_profit = round(suggested - fee.total - tax_amount - unit_costs, 2) if suggested else None
    margin = (unit_profit / suggested) if suggested else None
    markup = (unit_profit / cost) if (cost and unit_profit is not None) else None
    breakeven = breakeven_price(marketplace, unit_costs, tax, plan=plan, logistic=logistic)

    with_sales = [s for s in stats if s.sales_per_day is not None]
    market_spd = sum(s.sales_per_day for s in with_sales) if with_sales else None
    units_month = market_spd * 30 if market_spd is not None else None
    revenue_month = None
    if with_sales:
        revenue_month = sum((s.sales_per_day or 0) * 30 * (s.price or 0) for s in with_sales)
    top_share = None
    if market_spd and market_spd > 0:
        top_share = max(s.sales_per_day for s in with_sales) / market_spd

    # Fatia esperada de mercado para um vendedor novo com 1 anuncio mediano:
    # 1/(n_vendedores+1), limitada a 20%. Conservador de proposito.
    n_sellers = len(sellers)
    expected_share = min(1.0 / (n_sellers + 1), 0.20) if n_sellers else None
    expected_units = units_month * expected_share if (units_month is not None and expected_share) else None
    expected_profit = expected_units * unit_profit if (expected_units is not None and unit_profit is not None) else None

    # --- componentes do score ---
    score_margin = _clamp((margin or 0) / MARGIN_FULL_SCORE * 100) if margin is not None else 0.0
    if margin is not None and margin < 0:
        score_margin = 0.0
        flags.append("margem negativa")
    score_unit_profit = _clamp((unit_profit or 0) / UNIT_PROFIT_FULL_SCORE * 100) if unit_profit is not None else 0.0
    if units_month is None:
        score_demand = 0.0
        flags.append("poucos dados de vendas")
    else:
        import math

        # escala logaritmica: 100 un/mes ~ 55 pts, 1000 ~ 86 pts, 3000+ = 100
        score_demand = _clamp(math.log10(1 + units_month) / math.log10(1 + DEMAND_FULL_SCORE) * 100)
    if n_sellers == 0:
        score_competition = 0.0
        flags.append("sem concorrentes vinculados")
    else:
        span = COMPETITION_MANY - COMPETITION_FEW
        score_competition = _clamp(100 - (n_sellers - COMPETITION_FEW) / span * 100)
        if top_share is not None and top_share > 0.6:
            score_competition *= 0.7
            flags.append("mercado concentrado em 1 vendedor")
    if len(stats) < 3:
        flags.append("menos de 3 anuncios comparados")
    if breakeven and price_median and breakeven > price_median:
        flags.append("preco de equilibrio acima da mediana do mercado")

    score = (
        WEIGHTS["margin"] * score_margin
        + WEIGHTS["demand"] * score_demand
        + WEIGHTS["competition"] * score_competition
        + WEIGHTS["unit_profit"] * score_unit_profit
    )
    if margin is not None and margin < 0:
        score = min(score, 25.0)  # nunca recomenda produto que da prejuizo

    return ProductScore(
        supplier_product_id=product.id,
        product_name=product.name,
        supplier_name=product.supplier.name if product.supplier else None,
        sku=product.sku,
        marketplace=marketplace,
        cost_price=cost,
        shipping_in=shipping_in,
        packaging_cost=packaging,
        tax_rate=tax,
        unit_costs=round(unit_costs, 2),
        n_listings=len(stats),
        n_sellers=n_sellers,
        price_min=price_min,
        price_p25=round(price_p25, 2) if price_p25 is not None else None,
        price_median=round(price_median, 2) if price_median is not None else None,
        price_max=price_max,
        suggested_price=round(suggested, 2) if suggested else None,
        fee_commission=fee.commission if fee else None,
        fee_fixed=round(fee.fixed_fee + fee.shipping_program, 2) if fee else None,
        fee_total=fee.total if fee else None,
        tax_amount=tax_amount,
        unit_profit=unit_profit,
        margin=round(margin, 4) if margin is not None else None,
        markup=round(markup, 4) if markup is not None else None,
        breakeven=breakeven,
        market_sales_per_day=round(market_spd, 2) if market_spd is not None else None,
        market_units_month=round(units_month, 1) if units_month is not None else None,
        market_revenue_month=round(revenue_month, 2) if revenue_month is not None else None,
        top_listing_share=round(top_share, 3) if top_share is not None else None,
        listings_with_sales_data=len(with_sales),
        expected_share=round(expected_share, 3) if expected_share is not None else None,
        expected_units_month=round(expected_units, 1) if expected_units is not None else None,
        expected_profit_month=round(expected_profit, 2) if expected_profit is not None else None,
        score_margin=round(score_margin, 1),
        score_demand=round(score_demand, 1),
        score_competition=round(score_competition, 1),
        score_unit_profit=round(score_unit_profit, 1),
        score=round(score, 1),
        flags=flags,
        listings=sorted(stats, key=lambda s: -(s.sales_per_day or 0)),
    )


def score_all(session, price_strategy: str = "median", plan_by_marketplace: dict | None = None) -> list[ProductScore]:
    """Calcula o score de todo produto do fornecedor que tenha anuncios vinculados,
    um resultado por (produto, marketplace)."""
    from sqlalchemy import select

    plan_by_marketplace = plan_by_marketplace or {}
    results: list[ProductScore] = []
    products = session.scalars(select(SupplierProduct)).all()
    for product in products:
        by_market: dict[str, list[MLListing]] = {}
        for watch in product.watches:
            listing = watch.ml_listing
            by_market.setdefault(listing.marketplace or "ml", []).append(listing)
        for marketplace, listings in by_market.items():
            results.append(
                score_product(
                    product,
                    listings,
                    marketplace,
                    plan=plan_by_marketplace.get(marketplace),
                    price_strategy=price_strategy,
                )
            )
    results.sort(key=lambda r: -r.score)
    return results
