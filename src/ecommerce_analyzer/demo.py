"""Dados FICTICIOS para testar o dashboard sem coletar nada.

Usa a planilha samples/exemplo_fornecedores.csv e gera anuncios inventados
(fonte "demo") nos tres marketplaces, com dois snapshots separados por 7 dias
para exercitar a estimativa de vendas por historico. Rode num banco separado:
  python -m ecommerce_analyzer.cli --db sqlite:///data/demo.db seed-demo
"""

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
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
# Mais vendidos FICTICIOS para a secao de garimpo reverso: (titulo, preco,
# vendidos ha 7 dias, vendidos hoje, vendas 30d). Metade casa com produtos
# de samples/exemplo_fornecedores.csv, metade nao existe no fornecedor.
BEST_SELLERS = {
    (MARKETPLACE_ML, "MLB1000", "Eletrônicos, Áudio e Vídeo (demo)"): [
        ("Fone De Ouvido Bluetooth I12 TWS Sem Fio Envio Imediato", 39.90, 5200, 5620, None),
        ("Caixa De Som Bluetooth Portátil À Prova D'água 20W", 89.90, 3100, 3390, None),
        ("Carregador Turbo USB-C 20W Original Cabo Incluso", 34.90, 2800, 3050, None),
        ("Controle Remoto Universal Para Smart TV", 24.90, 2500, 2610, None),
        ("Smartwatch D20 Relógio Inteligente Bluetooth Monitor Cardíaco", 69.90, 1900, 2080, None),
        ("Cabo HDMI 2.0 4K Ultra HD 3 Metros", 19.90, 1500, 1580, None),
    ],
    (MARKETPLACE_SHOPEE, "11059983", "Casa e Decoração (demo)"): [
        ("Garrafa Térmica Inox 500ml Parede Dupla Quente e Frio", 32.90, 8100, 8600, 2100),
        ("Kit 6 Potes Herméticos de Vidro com Tampa", 49.90, 6400, 6700, 1300),
        ("Organizador De Gaveta Com 6 Divisórias Multiuso", 15.90, 5900, 6350, 1900),
        ("Tapete Antiderrapante Para Banheiro Super Absorvente", 22.90, 4300, 4450, 640),
        ("Mini Liquidificador Portátil USB Recarregável 6 Lâminas", 54.90, 3800, 4010, 900),
        ("Escorredor De Louça Inox Com Porta Talheres", 64.90, 2100, 2160, 260),
    ],
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
    bs, bs_found = _seed_best_sellers(session, rnd, now, week_ago)
    return {"listings": n_listings, "snapshots": session.query(MLListingSnapshot).count(),
            "best_sellers": bs, "best_sellers_found": bs_found}


def _seed_best_sellers(session: Session, rnd: random.Random, now: datetime, week_ago: datetime) -> tuple[int, int]:
    """Grava os mais vendidos ficticios (2 snapshots, 7 dias) e casa com o catalogo."""
    from .discovery import match_catalog, store_discovered

    total = found = 0
    for (mk, cat_id, cat_name), items in BEST_SELLERS.items():
        ids = [f"MLB8{rnd.randint(10**8, 10**9 - 1)}" if mk == MARKETPLACE_ML else f"shopee:demo_{rnd.randint(10**8, 10**9 - 1)}"
               for _ in items]

        def batch(sold_idx):
            return [
                {"id": ext, "marketplace": mk, "title": t, "price": price, "rank": rank,
                 "sold_quantity": row[sold_idx], "sold_30d": row[4], "free_shipping": True,
                 "seller_nickname": f"LOJA_DEMO_{rnd.randint(1, 40)}",
                 "date_created": (now - timedelta(days=rnd.randint(60, 700))).isoformat()}
                for rank, (ext, row) in enumerate(zip(ids, items), 1)
                for t, price in [(row[0], row[1])]
            ]

        old = store_discovered(session, batch(2), mk, cat_id, cat_name, extra={"demo": True})
        for snap in session.scalars(select(MLListingSnapshot).where(MLListingSnapshot.listing_id.in_([l.id for l in old]))):
            snap.captured_at = week_ago
        session.flush()
        listings = store_discovered(session, batch(3), mk, cat_id, cat_name, extra={"demo": True})
        for listing in listings:
            total += 1
            if match_catalog(session, listing):
                found += 1
    session.flush()
    session.expire_all()
    return total, found
