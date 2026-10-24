from ecommerce_analyzer.importer import import_csv
from ecommerce_analyzer.matcher import similarity
from ecommerce_analyzer.models import MLListing, SupplierProduct
from ecommerce_analyzer.suppliers_import import detect_columns, import_suppliers, parse_money


def test_similarity_modelo_diferente_nao_casa():
    assert similarity("fone bluetooth i12", "Fone De Ouvido Bluetooth I12 Tws") == 1.0
    assert similarity("fone bluetooth i12", "Fone Bluetooth I7s") < 0.6
    assert similarity("garrafa termica 500ml", "Garrafa Térmica 1 Litro") < 0.6


def test_parse_money():
    assert parse_money("R$ 1.234,56") == 1234.56
    assert parse_money("12,9") == 12.9
    assert parse_money("1,234.50") == 1234.5
    assert parse_money(None) is None


def test_detect_columns_sinonimos():
    m = detect_columns(["Fornecedor", "Descrição do Produto", "Cód.", "Preço Unitário (R$)", "Qtd Mínima"])
    assert m["name"] == "Descrição do Produto" and m["cost_price"] == "Preço Unitário (R$)"
    assert m["moq"] == "Qtd Mínima" and m["sku"] == "Cód."


def test_import_suppliers_idempotente(session):
    r1 = import_suppliers(session, "samples/exemplo_fornecedores.csv")
    r2 = import_suppliers(session, "samples/exemplo_fornecedores.csv")
    assert r1["created"] == 10 and r2["created"] == 0 and r2["updated"] == 10
    p = session.query(SupplierProduct).filter_by(sku="ALF-001").one()
    assert p.cost_price == 14.90 and p.shipping_cost == 1.20 and p.moq == 50


def test_import_csv_ferramenta_paga(session):
    r = import_csv(session, "samples/exemplo_import.csv", source="avante_pro")
    assert r["imported"] == 2
    listing = session.query(MLListing).filter_by(ml_item_id="MLB1234567890").one()
    snap = listing.snapshots[-1]
    assert snap.sold_30d == 320 and snap.price == 89.90
    assert snap.extra_data["posicao_patrocinado"] == 2
