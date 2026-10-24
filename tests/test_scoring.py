from datetime import datetime, timedelta, timezone

from ecommerce_analyzer.collector import add_snapshot, link, upsert_listing
from ecommerce_analyzer.models import Supplier, SupplierProduct
from ecommerce_analyzer.scoring import estimate_sales_per_day, score_all


def _product(session, cost=20.0):
    sup = Supplier(name="F")
    session.add(sup)
    session.flush()
    p = SupplierProduct(supplier_id=sup.id, name="Produto X", cost_price=cost, shipping_cost=1, packaging_cost=1, tax_rate=0.06)
    session.add(p)
    session.flush()
    return p


def _listing(session, ext, price, sold_before, sold_after, days=7, seller=None):
    l = upsert_listing(session, {"id": ext, "title": "Produto X", "seller_nickname": seller or ext})
    s1 = add_snapshot(session, l, {"price": price, "sold_quantity": sold_before}, "t")
    s1.captured_at = datetime.now(timezone.utc) - timedelta(days=days)
    add_snapshot(session, l, {"price": price, "sold_quantity": sold_after}, "t")
    session.flush()
    session.refresh(l)
    return l


def test_vendas_por_dia_pelo_historico(session):
    l = _listing(session, "MLB1", 80, 100, 170)
    spd, method = estimate_sales_per_day(l)
    assert method == "historico" and abs(spd - 10) < 0.01


def test_score_produto_lucrativo_vs_prejuizo(session):
    bom = _product(session, cost=20)
    for i in range(5):
        link(session, bom.id, _listing(session, f"MLB{i}", 89.9, 1000, 1000 + 70 * (i + 1)))
    ruim = _product(session, cost=85)
    for i in range(5, 8):
        link(session, ruim.id, _listing(session, f"MLB{i}", 89.9, 100, 110))
    res = {r.supplier_product_id: r for r in score_all(session)}
    assert res[bom.id].unit_profit > 30 and res[bom.id].score > 60
    assert res[ruim.id].unit_profit < 0 and res[ruim.id].score <= 25
    assert "margem negativa" in res[ruim.id].flags
    assert res[bom.id].market_units_month > 0
