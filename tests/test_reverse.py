"""Garimpo reverso: parsers puros, descoberta (API mockada), casamento e oportunidades."""

import pytest

from ecommerce_analyzer import collector, discovery, ml_api, supplier_search
from ecommerce_analyzer.models import MLListing, MLListingSnapshot, ProductWatch, Supplier, SupplierProduct
from ecommerce_analyzer.scraper import parse_ml_best_sellers, parse_shopee_category_tree
from ecommerce_analyzer.supplier_search import parse_supplier_results, query_from_title
from ecommerce_analyzer.suppliers_import import import_suppliers

BASE = "https://atacado.exemplo.com/busca?q=fone"


# ------------------------------------------------------------ query_from_title
def test_query_from_title_tira_marketing_e_mantem_ordem():
    assert query_from_title("Fone De Ouvido Bluetooth I12 TWS Sem Fio Envio Imediato Lançamento") == "fone ouvido bluetooth i12 tws"
    assert query_from_title("Garrafa Térmica Inox 500ml Original Garrafa Térmicas") == "garrafa térmica inox 500ml"
    assert query_from_title("Carregador Turbo USB-C 20W Pronta Entrega Frete Grátis") == "carregador turbo usb-c 20w"
    assert len(query_from_title("a b c d e f g h i j k l m n o p q r s t u v", max_words=3).split()) <= 3


# ------------------------------------------------------------ parse_supplier_results
def test_parse_supplier_com_seletores():
    html = """
    <div class="vitrine">
      <div class="prod"><a class="nome" href="/p/fone-i12">Fone Bluetooth TWS i12 Branco</a>
        <span class="preco">R$ 15,90</span><span class="ref">ALF-001</span></div>
      <div class="prod"><a class="nome" href="https://atacado.exemplo.com/p/fone-i7">Fone Bluetooth i7s</a>
        <span class="preco">R$ 1.299,00</span></div>
    </div>"""
    sel = {"item": "div.prod", "title": "a.nome", "price": "span.preco", "link": "a.nome", "sku": "span.ref"}
    r = parse_supplier_results(html, BASE, sel)
    assert r[0] == {"title": "Fone Bluetooth TWS i12 Branco", "price": 15.90, "url": "https://atacado.exemplo.com/p/fone-i12", "sku": "ALF-001"}
    assert r[1]["price"] == 1299.0 and r[1]["sku"] is None


def test_parse_supplier_json_ld():
    html = """<html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"ItemList","itemListElement":[
      {"@type":"ListItem","position":1,"item":{"@type":"Product","name":"Fone Bluetooth TWS i12","sku":"X12",
        "url":"/produto/fone-i12","offers":{"@type":"Offer","price":"14.90","priceCurrency":"BRL"}}},
      {"@type":"ListItem","position":2,"item":{"@type":"Product","name":"Smartwatch D20",
        "url":"https://atacado.exemplo.com/produto/d20","offers":[{"@type":"AggregateOffer","lowPrice":32.5}]}}
    ]}</script></head><body><div>R$ 99,00 <a href="/outro">Produto qualquer da vitrine</a></div></body></html>"""
    r = parse_supplier_results(html, BASE)
    assert [x["title"] for x in r] == ["Fone Bluetooth TWS i12", "Smartwatch D20"]
    assert r[0]["price"] == 14.90 and r[0]["sku"] == "X12" and r[0]["url"] == "https://atacado.exemplo.com/produto/fone-i12"
    assert r[1]["price"] == 32.5


def test_parse_supplier_heuristica():
    html = """<body><header><a href="/carrinho">Meu carrinho de compras</a></header>
    <ul class="lista">
      <li><a href="/p/1"><img src="a.jpg"></a><a href="/p/1">Fone Bluetooth TWS i12 Preto</a>
          <s>R$ 29,90</s> <span>por</span> <span class="v">R$</span><span>14,90</span> <small>3x de R$ 4,97</small> Cód: ALF-001</li>
      <li><div><h3><a href="/p/2" title="Carregador Turbo USB-C 20W">Carregador Turbo USB-C 20W</a></h3></div>
          <div><span>De R$ 30,00 por R$ 11,00</span></div></li>
      <li><a href="/p/1">Fone Bluetooth TWS i12 Preto</a> <b>R$ 14,90</b></li>
    </ul></body>"""
    r = parse_supplier_results(html, "https://atacado.exemplo.com/busca?q=x")
    assert len(r) == 2  # dedup pelo href
    assert r[0] == {"title": "Fone Bluetooth TWS i12 Preto", "price": 14.90, "url": "https://atacado.exemplo.com/p/1", "sku": "ALF-001"}
    assert r[1]["title"] == "Carregador Turbo USB-C 20W" and r[1]["price"] == 11.0


# ------------------------------------------------------------ categorias e mais vendidos (parsers)
def test_parse_shopee_category_tree():
    payload = {"error": 0, "data": {"category_list": [
        {"catid": 100, "parent_catid": 0, "name": "home", "display_name": "Casa e Decoração", "level": 1,
         "children": [{"catid": 101, "parent_catid": 100, "display_name": "Cozinha", "level": 2},
                      {"catid": 102, "name": "Banheiro", "children": [{"catid": 103, "name": "Toalhas"}]}]},
        {"catid": 200, "display_name": "Celulares"},
    ]}}
    cats = {c["id"]: c for c in parse_shopee_category_tree(payload)}
    assert cats["100"] == {"id": "100", "name": "Casa e Decoração", "parent_id": None, "level": 1}
    assert cats["101"]["parent_id"] == "100" and cats["101"]["level"] == 2
    assert cats["102"]["parent_id"] == "100" and cats["103"] == {"id": "103", "name": "Toalhas", "parent_id": "102", "level": 3}
    assert cats["200"]["level"] == 1 and len(cats) == 5


def test_parse_ml_best_sellers_rank_e_catalogo():
    card = """<div class="poly-card"><a class="poly-component__title" href="https://www.mercadolivre.com.br/fone/p/MLB{n}">Produto {n}</a>
      <div class="poly-price__current"><span class="andes-money-amount__fraction">{p}</span></div><span>+{v} vendidos</span></div>"""
    html = "<h1>Mais vendidos em Fones de Ouvido</h1>" + "".join(card.format(n=12345670 + i, p=40 + i, v=1000) for i in range(3))
    items = parse_ml_best_sellers(html, "MLB1000")
    assert [i["rank"] for i in items] == [1, 2, 3]
    assert items[0]["id"] == "MLB12345670" and items[0]["catalog_product_id"] == "MLB12345670"
    assert items[0]["category_id"] == "MLB1000" and items[0]["category_name"] == "Fones de Ouvido"
    assert items[2]["price"] == 42 and items[2]["sold_quantity"] == 1000


# ------------------------------------------------------------ descoberta ML (API mockada)
def test_descoberta_ml_api_grava_fonte_e_rank(session, monkeypatch):
    monkeypatch.setattr(ml_api, "get_category", lambda c: {"id": c, "name": "Fones"})
    monkeypatch.setattr(ml_api, "get_category_highlights", lambda c: [
        {"id": "MLB111", "position": 1, "type": "ITEM"},
        {"id": "MLB-PROD", "position": 2, "type": "PRODUCT"},
    ])
    monkeypatch.setattr(ml_api, "get_product_items", lambda pid: [{"item_id": "MLB222"}])
    monkeypatch.setattr(ml_api, "get_items_details_bulk", lambda ids: {
        i: {"id": i, "title": f"Anuncio {i}", "price": 50.0, "category_id": "MLB1001", "permalink": f"https://x/{i}"} for i in ids
    })
    listings = discovery.discover_ml_api(session, "MLB1000")
    assert [l.ml_item_id for l in listings] == ["MLB111", "MLB222"]
    snaps = session.query(MLListingSnapshot).order_by(MLListingSnapshot.id).all()
    assert {s.source for s in snaps} == {"mais_vendidos_ml"}
    assert [s.extra_data for s in snaps] == [{"categoria": "MLB1000", "rank": 1}, {"categoria": "MLB1000", "rank": 2}]
    assert listings[0].category_name == "Fones"


# ------------------------------------------------------------ casamento reverso
def _best_seller(session, ext, title, price, mk="ml", rank=1, cat="MLB1000"):
    discovery.store_discovered(session, [{"id": ext, "marketplace": mk, "title": title, "price": price, "rank": rank}], mk, cat)
    return session.query(MLListing).filter_by(ml_item_id=ext).one()


def test_casamento_no_catalogo(session):
    import_suppliers(session, "samples/exemplo_fornecedores.csv")
    fone = _best_seller(session, "MLB900", "Fone De Ouvido Bluetooth I12 Tws Sem Fio", 39.9)
    panela = _best_seller(session, "MLB901", "Panela De Pressão Elétrica 5 Litros", 299.0, rank=2)
    alfa = session.query(Supplier).filter_by(name="Distribuidora Alfa").one()
    rows = discovery.reverse_match(session, [fone, panela], supplier_id=alfa.id)
    assert rows[0]["status"] == "encontrado" and rows[0]["product_name"] == "Fone Bluetooth TWS i12"
    assert rows[0]["cost_price"] == 14.90 and rows[0]["origin"] == "catalogo"
    assert rows[1]["status"] == "nao_encontrado"
    assert session.query(ProductWatch).count() == 1
    # outro fornecedor nao tem o fone
    beta = session.query(Supplier).filter_by(name="Importadora Beta").one()
    assert discovery.match_catalog(session, fone, supplier_id=beta.id) is None


def test_casamento_via_site_do_fornecedor(session, monkeypatch):
    sup = Supplier(name="Atacado Web", search_url="https://atacado.exemplo.com/busca?q={q}")
    session.add(sup)
    session.flush()
    listing = _best_seller(session, "MLB902", "Caixa De Som Bluetooth Portátil 20W Envio Imediato", 89.9)
    calls = []

    def fake_search(supplier, query, ctx=None, use_browser=True, headless=False):
        calls.append(query)
        return [
            {"title": "Capa para celular", "price": 3.0, "url": "https://atacado.exemplo.com/p/capa", "sku": None},
            {"title": "Caixa de Som Bluetooth Portatil 20W Preta", "price": 31.5, "url": "https://atacado.exemplo.com/p/cx20", "sku": "CX20"},
        ]

    monkeypatch.setattr(supplier_search, "search_supplier", fake_search)
    rows = discovery.reverse_match(session, [listing], supplier_id=sup.id, use_browser=False)
    assert calls == ["caixa som bluetooth portátil 20w"]
    assert rows[0]["status"] == "encontrado" and rows[0]["origin"] == "site" and rows[0]["cost_price"] == 31.5
    sp = session.query(SupplierProduct).filter_by(supplier_id=sup.id).one()
    assert sp.url == "https://atacado.exemplo.com/p/cx20" and sp.sku == "CX20" and sp.search_terms == calls[0]
    assert sp.notes.startswith("encontrado na busca do site em ")
    w = session.query(ProductWatch).filter_by(supplier_product_id=sp.id, ml_listing_id=listing.id).one()
    assert w.match_score == 1.0
    # rodar de novo nao duplica o produto (achado no catalogo agora)
    discovery.reverse_match(session, [listing], supplier_id=sup.id, use_browser=False)
    assert session.query(SupplierProduct).filter_by(supplier_id=sup.id).count() == 1 and len(calls) == 1


# ------------------------------------------------------------ oportunidades
def test_list_opportunities_com_lucro(session):
    sup = Supplier(name="F")
    session.add(sup)
    session.flush()
    p = SupplierProduct(supplier_id=sup.id, name="Garrafa Termica 500ml", cost_price=20, shipping_cost=1,
                        packaging_cost=1, tax_rate=0.06)
    session.add(p)
    session.flush()
    ok = _best_seller(session, "MLB903", "Garrafa Térmica 500ml Inox", 100.0)
    _best_seller(session, "MLB904", "Produto que ninguem tem", 50.0, rank=2)
    # anuncio comum (sem fonte mais_vendidos) nao entra
    comum = collector.upsert_listing(session, {"id": "MLB905", "title": "Outro"})
    collector.add_snapshot(session, comum, {"price": 10}, "ml_api")
    collector.link(session, p.id, ok, match_score=0.9)
    session.flush()
    session.expire_all()

    rows = discovery.list_opportunities(session)
    assert [r["ml_item_id"] for r in rows] == ["MLB903", "MLB904"]
    r = rows[0]
    # 100 - 13% ML classico (sem taxa fixa acima de R$79) - 6% imposto - (20 + 1 + 1)
    assert r["status"] == "encontrado" and r["supplier_name"] == "F" and r["category_id"] == "MLB1000"
    assert r["fee_total"] == 13.0 and r["tax_amount"] == 6.0 and r["unit_profit"] == pytest.approx(59.0)
    assert r["margin"] == pytest.approx(0.59) and r["rank"] == 1
    assert rows[1]["status"] == "nao_encontrado" and rows[1]["unit_profit"] is None
    assert [x["ml_item_id"] for x in discovery.list_opportunities(session, only_missing=True)] == ["MLB904"]
    assert discovery.list_opportunities(session, category="MLB999") == []


def test_category_from_url():
    assert discovery.category_from_url("https://www.mercadolivre.com.br/mais-vendidos/MLB1055") == "MLB1055"
    assert discovery.category_from_url("https://shopee.com.br/Casa-e-Decoracao-cat.11059983?sortBy=sales") == "11059983"
    assert discovery.category_from_url("https://shopee.com.br/x-cat.100.101?sortBy=sales") == "101"
