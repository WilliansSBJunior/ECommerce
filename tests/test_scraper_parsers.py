from ecommerce_analyzer.scraper import (
    parse_ml_item_page,
    parse_ml_search,
    parse_shopee_payloads,
    parse_sold_text,
    parse_tiktok_payloads,
)

ML_HTML = """
<ol><li class="ui-search-layout__item"><div class="poly-card">
  <h3 class="poly-component__title-wrapper"><a class="poly-component__title" href="https://produto.mercadolivre.com.br/MLB-1234567890-fone-i12-_JM#pos">Fone Bluetooth I12 Tws</a></h3>
  <span class="poly-component__seller">Por LOJA X</span>
  <span class="poly-reviews__rating">4.6</span><span class="poly-reviews__total">(1.234)</span>
  <span class="poly-phrase-label">+5mil vendidos</span>
  <s class="andes-money-amount--previous"><span class="andes-money-amount__fraction">99</span></s>
  <div class="poly-price__current"><span class="andes-money-amount__fraction">49</span><span class="andes-money-amount__cents">90</span></div>
  <div class="poly-component__shipping">Frete grátis FULL</div>
</div></li></ol>
"""


def test_parse_sold_text():
    assert parse_sold_text("+10mil vendidos") == 10000
    assert parse_sold_text("1,5 mil vendidos") == 1500
    assert parse_sold_text("+500 vendidos") == 500
    assert parse_sold_text("Novo") is None


def test_parse_ml_search():
    (item,) = parse_ml_search(ML_HTML, "fone i12")
    assert item["id"] == "MLB1234567890"
    assert item["price"] == 49.90 and item["original_price"] == 99
    assert item["sold_quantity"] == 5000 and item["reviews_count"] == 1234 and item["rating"] == 4.6
    assert item["free_shipping"] and item["logistic_type"] == "fulfillment"
    assert item["seller_nickname"] == "LOJA X" and item["permalink"].endswith("_JM")


def test_parse_ml_item_page():
    html = '<span class="ui-pdp-subtitle">Novo | +1000 vendidos</span><script type="application/ld+json">{"@type":"Product","offers":{"price":59.9},"aggregateRating":{"ratingValue":4.8,"reviewCount":321}}</script>'
    d = parse_ml_item_page(html)
    assert d == {"sold_quantity": 1000, "condition": "new", "price": 59.9, "rating": 4.8, "reviews_count": 321}


def test_parse_shopee():
    payload = {"items": [{"item_basic": {"itemid": 22, "shopid": 11, "name": "Garrafa 500ml", "price": 2990000,
                                         "historical_sold": 4300, "sold": 610, "item_rating": {"rating_star": 4.9, "rating_count": [100, 1, 2, 3, 4, 90]}}}]}
    (p,) = parse_shopee_payloads([payload])
    assert p["id"] == "shopee:11_22" and p["price"] == 29.9
    assert p["sold_quantity"] == 4300 and p["sold_30d"] == 610 and p["reviews_count"] == 100


def test_parse_tiktok():
    payload = {"data": {"products": [{"product_id": "1729384756123456789", "title": "Mini Liquidificador",
                                      "product_price_info": {}, "price": {"sale_price": "R$ 59,90"},
                                      "sold_info": {"sold_count": 2300}, "seller_info": {"shop_name": "Loja T"}}]}}
    (p,) = parse_tiktok_payloads([payload])
    assert p["id"] == "tiktok:1729384756123456789" and p["price"] == 59.9
    assert p["sold_quantity"] == 2300 and p["seller_nickname"] == "Loja T"
