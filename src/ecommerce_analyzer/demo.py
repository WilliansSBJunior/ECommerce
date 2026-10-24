"""Dados FICTICIOS para testar o dashboard sem coletar nada.

Usa a planilha samples/exemplo_fornecedores.csv e gera anuncios inventados
(fonte "demo") nos tres marketplaces, com dois snapshots separados por 7 dias
para exercitar a estimativa de vendas por historico. Rode num banco separado:
  python -m ecommerce_analyzer.cli --db sqlite:///data/demo.db seed-demo
"""

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .collector import add_snapshot, link, upsert_listing
from .models import MARKETPLACE_ML, MARKETPLACE_SHOPEE, MARKETPLACE_TIKTOK, MLListingSnapshot, SupplierProduct
from .suppliers_import import import_suppliers

# preco de mercado (multiplo do custo) e demanda diaria tipica por anuncio
PROFILES = {
    "ALF-001": (3.2, 40), "ALF-002": (2.6, 18), "ALF-003": (3.0, 35), "BET-010": (2.4, 12),
    "BET-011": (2.1, 9), "BET-012": (4.0, 25), "BET-013": (1.7, 4), "GAM-100": (2.2, 15),
    "GAM-101": (3.4, 30), "GAM-102": (1.5, 6),
}
MARKET_FACTOR = {MARKETPLACE_ML: (1.0, 1.0), MARKETPLACE_SHOPEE: (0.85, 1.3), MARKETPLACE_TIKTOK: (0.9, 0.7)}


def seed_demo(session: Session, suppliers_file: str = "samples/exemplo_fornecedores.csv", seed: int = 42) -> dict:
    rnd = random.Random(seed)
    import_suppliers(session, suppliers_file)
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    n_listings = 0
    for product in session.query(SupplierProduct).all():
        mult, demand = PROFILES.get(product.sku, (2.5, 10))
        for mk, (price_f, demand_f) in MARKET_FACTOR.items():
            n = rnd.randint(4, 14) if mk == MARKETPLACE_ML else rnd.randint(3, 10)
            for i in range(n):
                ext = f"MLB9{rnd.randint(10**8, 10**9 - 1)}" if mk == MARKETPLACE_ML else f"{mk}:demo{rnd.randint(10**8, 10**9 - 1)}"
                price = round(product.cost_price * mult * price_f * rnd.uniform(0.8, 1.25), 2)
                daily = max(0.0, demand * demand_f * rnd.lognormvariate(-0.3, 0.8) / (1 + i * 0.35))
                total_before = rnd.randint(50, 4000)
                listing = upsert_listing(
                    session,
                    {
                        "id": ext,
                        "marketplace": mk,
                        "title": f"{product.name} {rnd.choice(['Original', 'Premium', 'Envio Imediato', 'Promoção', ''])}".strip(),
                        "seller_nickname": f"LOJA_DEMO_{rnd.randint(1, 40)}",
                        "permalink": None,
                        "date_created": (now - timedelta(days=rnd.randint(30, 600))).isoformat(),
                    },
                )
                first = add_snapshot(
                    session, listing,
                    {"price": price, "sold_quantity": total_before, "position": i + 1,
                     "sold_30d": int(daily * 30) if mk == MARKETPLACE_SHOPEE else None},
                    "demo",
                )
                first.captured_at = week_ago
                add_snapshot(
                    session, listing,
                    {"price": price, "sold_quantity": total_before + int(daily * 7), "position": i + 1,
                     "sold_30d": int(daily * 30) if mk == MARKETPLACE_SHOPEE else None,
                     "free_shipping": True, "logistic_type": rnd.choice(["fulfillment", "xd_drop_off", None])},
                    "demo",
                )
                link(session, product.id, listing, match_score=1.0)
                n_listings += 1
    session.flush()
    return {"listings": n_listings, "snapshots": session.query(MLListingSnapshot).count()}
