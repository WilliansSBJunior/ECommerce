"""Extrator via navegador para Mercado Livre, Shopee e TikTok Shop.

Faz o mesmo que as extensoes tipo Avante Pro: abre a pagina de busca no seu
navegador, ja logado, e le os dados que a propria pagina carrega.

- Mercado Livre: le os cards da busca (titulo, preco, "+1000 vendidos",
  avaliacao, frete gratis, FULL). Com --details visita cada anuncio para ler
  o contador de vendidos da pagina do produto.
- Shopee e TikTok Shop: a pagina carrega os produtos por chamadas JSON
  internas; o extrator escuta essas respostas e guarda vendidos (total e
  mensal), preco, avaliacoes e loja.

Por que precisa do SEU navegador logado: os tres sites bloqueiam acesso
automatizado sem sessao (o ML manda para "account-verification", a Shopee e o
TikTok devolvem a pagina sem produtos). Por isso o perfil do navegador fica em
data/browser_profile e o primeiro uso e com --login para voce entrar na conta.

Use com moderacao (dezenas de buscas por dia, nao milhares): e o seu login
que esta sendo usado, e os termos de uso dos marketplaces restringem coleta
automatizada. A API oficial do ML (comando `collect`) e sempre preferivel.

As funcoes parse_* sao puras (recebem HTML/JSON) para permitir teste offline
com os arquivos salvos em data/raw/. Seletores ficam todos em SELECTORS.
"""

import json
import os
import re
import time
import unicodedata
from datetime import datetime
from urllib.parse import quote

from bs4 import BeautifulSoup

from . import config
from .models import MARKETPLACE_ML, MARKETPLACE_SHOPEE, MARKETPLACE_TIKTOK

SELECTORS = {
    "ml": {
        "card": "li.ui-search-layout__item, div.poly-card, div.ui-search-result__wrapper",
        "title": "a.poly-component__title, h2.poly-box a, h3.poly-component__title-wrapper a, a.ui-search-item__group__element, h2.ui-search-item__title",
        "price_current": "div.poly-price__current, div.ui-search-price__second-line, span.andes-money-amount--cents-superscript",
        "price_original": "s.andes-money-amount--previous, s.ui-search-price__original-value",
        "fraction": "span.andes-money-amount__fraction",
        "cents": "span.andes-money-amount__cents",
        "rating": "span.poly-reviews__rating, span.ui-search-reviews__rating-number",
        "reviews": "span.poly-reviews__total, span.ui-search-reviews__amount",
        "seller": "span.poly-component__seller, p.ui-search-official-store-label",
        "shipping": "div.poly-component__shipping, p.ui-search-item__shipping",
        "full_icon": "svg[aria-label*='FULL' i], span.poly-component__shipped-from, [class*='fulfillment']",
        "thumbnail": "img",
        # pagina do anuncio
        "pdp_subtitle": "span.ui-pdp-subtitle",
        "pdp_seller": "div.ui-pdp-seller__header__title, span.ui-pdp-seller__label-sold + span, a.ui-pdp-action-modal__link",
        # pagina publica de mais vendidos (/mais-vendidos/MLBxxxx): os cards sao
        # os mesmos poly-card da busca; o titulo da pagina traz a categoria.
        # NAO validado ao vivo (o site pede login a partir do servidor).
        "best_seller_category": "h1.ui-search-breadcrumb__title, h1",
    },
}

# Chaves que vao para MLListing (o resto vai para o snapshot).
LISTING_KEYS = {
    "id", "marketplace", "title", "category_id", "category_name", "catalog_product_id",
    "seller_id", "seller_nickname", "permalink", "thumbnail", "currency", "date_created",
}

ML_ITEM_ID_RE = re.compile(r"(MLB)-?(\d{6,})")
SOLD_RE = re.compile(r"\+?\s*(?:mais de\s*)?(\d+(?:[.,]\d+)?)\s*(mil|k)?\s*vendid", re.I)


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def parse_sold_text(text: str | None) -> int | None:
    """'+10mil vendidos' -> 10000 ; '+1000 vendidos' -> 1000 ; '1,5 mil vendidos' -> 1500.
    O ML mostra faixas ('+5mil'), entao o valor e o limite inferior da faixa."""
    if not text:
        return None
    m = SOLD_RE.search(text)
    if not m:
        return None
    number = m.group(1)
    if m.group(2):
        value = float(number.replace(",", "."))
        return int(round(value * 1000))
    return int(number.replace(".", "").replace(",", ""))


def _price_from(node) -> float | None:
    if node is None:
        return None
    frac = node.select_one(SELECTORS["ml"]["fraction"])
    if frac is None:
        return None
    cents = node.select_one(SELECTORS["ml"]["cents"])
    try:
        value = float(_clean(frac.get_text()).replace(".", ""))
    except ValueError:
        return None
    if cents is not None and _clean(cents.get_text()).isdigit():
        value += int(_clean(cents.get_text())) / 100
    return value


def parse_ml_search(html: str, query: str | None = None) -> list[dict]:
    """Extrai os cards de uma pagina de busca do ML. Retorna dicts normalizados
    com as chaves usadas por collector.upsert_listing/add_snapshot."""
    soup = BeautifulSoup(html, "html.parser")
    sel = SELECTORS["ml"]
    results, seen = [], set()
    cards = soup.select(sel["card"])
    for card in cards:
        link = card.select_one(sel["title"]) or card.select_one("a[href*='MLB']")
        if link is None:
            continue
        href = link.get("href") or ""
        m = ML_ITEM_ID_RE.search(href) or ML_ITEM_ID_RE.search(str(card))
        if not m:
            continue
        item_id = f"{m.group(1)}{m.group(2)}"
        if item_id in seen:
            continue
        seen.add(item_id)
        text = _clean(card.get_text(" "))
        price_node = card.select_one(sel["price_current"])
        price = _price_from(price_node) or _price_from(card)
        original = _price_from(card.select_one(sel["price_original"]))
        rating_node = card.select_one(sel["rating"])
        reviews_node = card.select_one(sel["reviews"])
        reviews = re.sub(r"\D", "", reviews_node.get_text()) if reviews_node else ""
        seller_node = card.select_one(sel["seller"])
        img = card.select_one(sel["thumbnail"])
        results.append(
            {
                "id": item_id,
                "marketplace": MARKETPLACE_ML,
                "title": _clean(link.get_text()) or item_id,
                "permalink": href.split("#")[0] if href.startswith("http") else None,
                "thumbnail": (img.get("data-src") or img.get("src")) if img else None,
                "seller_nickname": re.sub(r"^(Por|Vendido por)\s+", "", _clean(seller_node.get_text())) if seller_node else None,
                "price": price,
                "original_price": original if original and price and original > price else None,
                "sold_quantity": parse_sold_text(text),
                "rating": float(_clean(rating_node.get_text()).replace(",", ".")) if rating_node and re.match(r"^\d", _clean(rating_node.get_text())) else None,
                "reviews_count": int(reviews) if reviews else None,
                "free_shipping": bool(re.search(r"frete gr[aá]tis|chegar[aá] gr[aá]tis|envio gr[aá]tis", text, re.I)),
                "logistic_type": "fulfillment" if card.select_one(sel["full_icon"]) or re.search(r"\bFULL\b", text) else None,
                "position": len(results) + 1,
                "search_query": query,
                "sponsored": bool(re.search(r"\bPatrocinado\b", text)),
            }
        )
    return results


def parse_ml_best_sellers(html: str, category_id: str | None = None) -> list[dict]:
    """Le a pagina publica de mais vendidos do ML (/mais-vendidos/MLBxxxx).

    Reaproveita parse_ml_search (cards poly-card). O link pode ser de catalogo
    (/p/MLB123) em vez do anuncio: o id fica MLB123 e vai tambem para
    catalog_product_id. `rank` = ordem do card na pagina (1 = mais vendido)."""
    items = parse_ml_search(html)
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one(SELECTORS["ml"]["best_seller_category"])
    category_name = _clean(h1.get_text()) if h1 else None
    if category_name:
        category_name = re.sub(r"^(Os\s+)?mais vendidos( em| de)?\s*", "", category_name, flags=re.I) or None
    for rank, item in enumerate(items, 1):
        item["rank"] = rank
        item["position"] = rank
        if item.get("permalink") and re.search(r"/p/MLB\d+", item["permalink"]):
            item["catalog_product_id"] = item["id"]
        if category_id:
            item["category_id"] = category_id
        if category_name:
            item["category_name"] = category_name
    return items


def parse_ml_item_page(html: str) -> dict:
    """Le a pagina do anuncio: '+5mil vendidos' (subtitulo) e JSON-LD (preco, nota)."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {}
    sub = soup.select_one(SELECTORS["ml"]["pdp_subtitle"])
    if sub:
        out["sold_quantity"] = parse_sold_text(sub.get_text())
        out["condition"] = "used" if "usado" in sub.get_text().lower() else "new"
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        for d in data if isinstance(data, list) else [data]:
            if not isinstance(d, dict) or d.get("@type") != "Product":
                continue
            offers = d.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if offers.get("price"):
                out["price"] = float(offers["price"])
            agg = d.get("aggregateRating") or {}
            if agg.get("ratingValue"):
                out["rating"] = float(agg["ratingValue"])
            if agg.get("reviewCount") or agg.get("ratingCount"):
                out["reviews_count"] = int(agg.get("reviewCount") or agg.get("ratingCount"))
    return out


def _walk(obj):
    """Percorre recursivamente qualquer JSON."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _num(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace("mil", "k")
    m = re.match(r"^\+?\s*([\d.,]+)\s*(k)?", text)
    if not m:
        return None
    base = m.group(1)
    if m.group(2):
        return float(base.replace(",", ".")) * 1000
    return float(base.replace(".", "").replace(",", ".")) if "," in base else float(base.replace(",", ""))


def parse_shopee_payloads(payloads: list, query: str | None = None) -> list[dict]:
    """Extrai produtos das respostas JSON da busca da Shopee (search_items e afins).

    Procura qualquer objeto com itemid + shopid + name. Precos da Shopee vem
    multiplicados por 100000. `sold` = vendas nos ultimos 30 dias,
    `historical_sold` = total."""
    results, seen = [], set()
    for payload in payloads:
        for d in _walk(payload):
            if not ("itemid" in d and "shopid" in d and ("name" in d or "title" in d)):
                continue
            key = f"shopee:{d['shopid']}_{d['itemid']}"
            if key in seen:
                continue
            seen.add(key)
            price = d.get("price") or d.get("price_min")
            price = price / 100000 if isinstance(price, (int, float)) and price > 100000 else price
            price_before = d.get("price_before_discount")
            price_before = price_before / 100000 if isinstance(price_before, (int, float)) and price_before > 100000 else price_before
            rating = d.get("item_rating") or {}
            name = d.get("name") or d.get("title")
            results.append(
                {
                    "id": key,
                    "marketplace": MARKETPLACE_SHOPEE,
                    "title": name,
                    "permalink": f"https://shopee.com.br/product/{d['shopid']}/{d['itemid']}",
                    "thumbnail": f"https://down-br.img.susercontent.com/file/{d['image']}" if d.get("image") else None,
                    "seller_id": str(d["shopid"]),
                    "seller_nickname": d.get("shop_name") or str(d["shopid"]),
                    "category_id": str(d.get("catid")) if d.get("catid") else None,
                    "date_created": datetime.fromtimestamp(d["ctime"]).isoformat() if d.get("ctime") else None,
                    "price": float(price) if price else None,
                    "original_price": float(price_before) if price_before else None,
                    "sold_quantity": int(_num(d.get("historical_sold")) or 0) if d.get("historical_sold") is not None else None,
                    "sold_30d": int(_num(d.get("sold"))) if d.get("sold") is not None else None,
                    "available_quantity": d.get("stock"),
                    "rating": rating.get("rating_star"),
                    # rating_count = [total, 1 estrela, ..., 5 estrelas]
                    "reviews_count": (rating.get("rating_count") or [None])[0] if isinstance(rating.get("rating_count"), list) else rating.get("rating_count"),
                    "official_store": bool(d.get("is_official_shop")),
                    "free_shipping": d.get("show_free_shipping"),
                    "position": len(results) + 1,
                    "search_query": query,
                }
            )
    return results


def parse_shopee_category_tree(payload) -> list[dict]:
    """Extrai a arvore de categorias da Shopee: [{id, name, parent_id, level}].

    Procura (recursivamente, inclusive em "children") dicts com `catid` e
    `display_name`/`name`. Pensado para a resposta de
    https://shopee.com.br/api/v4/pages/get_category_tree, que NAO foi validada
    ao vivo (a Shopee bloqueia o servidor): o formato esperado e
    {"data": {"category_list": [{"catid", "parent_catid", "name",
    "display_name", "level", "children": [...]}]}}. Se mudar, a funcao ainda
    acha qualquer lista de dicts com catid em qualquer nivel do JSON."""
    out: list[dict] = []
    seen: set[str] = set()

    def visit(obj, parent_id, level):
        if isinstance(obj, list):
            for v in obj:
                visit(v, parent_id, level)
            return
        if not isinstance(obj, dict):
            return
        name = obj.get("display_name") or obj.get("name")
        if obj.get("catid") is not None and isinstance(name, str):
            cid = str(obj["catid"])
            parent = obj.get("parent_catid") or obj.get("parent_id")
            parent = str(parent) if parent not in (None, 0, "0", "") else parent_id
            lvl = obj.get("level") if isinstance(obj.get("level"), int) else level
            if cid not in seen:
                seen.add(cid)
                out.append({"id": cid, "name": _clean(name), "parent_id": parent, "level": lvl})
            for v in obj.values():
                if isinstance(v, (list, dict)):
                    visit(v, cid, lvl + 1)
            return
        for v in obj.values():
            visit(v, parent_id, level)

    visit(payload, None, 1)
    return out


TIKTOK_ID_KEYS = ("product_id", "productId", "id")
TIKTOK_TITLE_KEYS = ("title", "product_name", "productName", "name")
TIKTOK_SOLD_KEYS = ("sold_count", "soldCount", "sold", "sales", "sale_count", "format_sold_count")


def _first(d: dict, keys) -> object:
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def _tiktok_price(d: dict) -> float | None:
    for key in ("price", "product_price", "sale_price", "real_price", "min_price", "price_info"):
        v = d.get(key)
        if isinstance(v, dict):
            v = _first(v, ("sale_price", "real_price", "price", "min_price", "sale_price_decimal", "sale_price_format"))
        num = _num(re.sub(r"[^\d.,]", "", str(v))) if v is not None else None
        if num:
            return num / 100 if isinstance(d.get(key), int) and num > 10000 else num
    return None


def parse_tiktok_payloads(payloads: list, query: str | None = None) -> list[dict]:
    """Extrai produtos das respostas JSON da busca do TikTok Shop.

    O TikTok muda o formato com frequencia; a funcao procura objetos que
    tenham id de produto + titulo + algum indicador de vendas ou preco."""
    results, seen = [], set()
    for payload in payloads:
        for d in _walk(payload):
            pid = _first(d, TIKTOK_ID_KEYS)
            title = _first(d, TIKTOK_TITLE_KEYS)
            if not pid or not isinstance(title, str) or not re.fullmatch(r"\d{10,}", str(pid)):
                continue
            sold_raw = _first(d, TIKTOK_SOLD_KEYS)
            if isinstance(sold_raw, dict):
                sold_raw = _first(sold_raw, ("sold_count", "count", "format_sold_count"))
            if sold_raw is None:
                sold_info = d.get("sold_info") or d.get("product_sold") or {}
                sold_raw = _first(sold_info, ("sold_count", "count", "format_sold_count")) if isinstance(sold_info, dict) else None
            price = _tiktok_price(d)
            if sold_raw is None and price is None:
                continue
            key = f"tiktok:{pid}"
            if key in seen:
                continue
            seen.add(key)
            seller = d.get("seller_info") or d.get("shop_info") or d.get("seller") or {}
            rating = d.get("rate_info") or d.get("rating_info") or {}
            image = d.get("image") or d.get("cover") or {}
            if isinstance(image, dict):
                urls = image.get("url_list") or []
                image = urls[0] if urls else None
            results.append(
                {
                    "id": key,
                    "marketplace": MARKETPLACE_TIKTOK,
                    "title": title,
                    "permalink": f"https://www.tiktok.com/view/product/{pid}",
                    "thumbnail": image if isinstance(image, str) else None,
                    "seller_id": str(_first(seller, ("seller_id", "shop_id", "id")) or "") or None if isinstance(seller, dict) else None,
                    "seller_nickname": _first(seller, ("shop_name", "seller_name", "name")) if isinstance(seller, dict) else None,
                    "price": price,
                    "sold_quantity": int(_num(sold_raw)) if _num(sold_raw) is not None else None,
                    "rating": _num(_first(rating, ("score", "rating", "star"))) if isinstance(rating, dict) else None,
                    "reviews_count": int(_num(_first(rating, ("review_count", "count")))) if isinstance(rating, dict) and _num(_first(rating, ("review_count", "count"))) else None,
                    "position": len(results) + 1,
                    "search_query": query,
                }
            )
    return results


# --------------------------------------------------------------------------
# Parte que usa o navegador (so roda na maquina do usuario)
# --------------------------------------------------------------------------

SEARCH_URLS = {
    MARKETPLACE_ML: lambda q: f"https://lista.mercadolivre.com.br/{slugify(q)}",
    MARKETPLACE_SHOPEE: lambda q: f"https://shopee.com.br/search?keyword={quote(q)}&sortBy=sales",
    MARKETPLACE_TIKTOK: lambda q: f"https://www.tiktok.com/shop/s/{quote(q)}",
}
LOGIN_URLS = {
    MARKETPLACE_ML: "https://www.mercadolivre.com.br/",
    MARKETPLACE_SHOPEE: "https://shopee.com.br/buyer/login",
    MARKETPLACE_TIKTOK: "https://www.tiktok.com/login",
}
JSON_HINTS = {
    MARKETPLACE_SHOPEE: ("search_items", "/api/v4/search", "recommend"),
    MARKETPLACE_TIKTOK: ("search", "product", "shop"),
}
BLOCK_HINTS = ("account-verification", "captcha", "/verify", "login")
# Garimpo reverso (paginas NAO validadas ao vivo: o site bloqueia o servidor).
ML_BEST_SELLERS_URL = "https://www.mercadolivre.com.br/mais-vendidos/{categoria}"
SHOPEE_CATEGORY_URL = "https://shopee.com.br/x-cat.{catid}?sortBy=sales"
SHOPEE_CATEGORY_TREE_URL = "https://shopee.com.br/api/v4/pages/get_category_tree"


class ScrapeBlocked(RuntimeError):
    """O site pediu login/captcha: rode de novo com --login e resolva na janela."""


def _save_raw(marketplace: str, query: str, html: str | None, payloads: list) -> str:
    os.makedirs(config.RAW_CAPTURE_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.join(config.RAW_CAPTURE_DIR, f"{marketplace}_{slugify(query)[:40]}_{stamp}")
    if html:
        with open(base + ".html", "w", encoding="utf-8") as fh:
            fh.write(html)
    if payloads:
        with open(base + ".json", "w", encoding="utf-8") as fh:
            json.dump(payloads, fh, ensure_ascii=False)
    return base


def open_browser(headless: bool = False):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright nao instalado. Rode: pip install playwright && playwright install chromium"
        ) from exc
    pw = sync_playwright().start()
    os.makedirs(config.BROWSER_PROFILE_DIR, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(
        config.BROWSER_PROFILE_DIR,
        headless=headless,
        locale="pt-BR",
        viewport={"width": 1366, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    return pw, ctx


def login(marketplace: str) -> None:
    """Abre a pagina de login e espera o usuario entrar na conta e apertar Enter."""
    pw, ctx = open_browser(headless=False)
    try:
        page = ctx.new_page()
        page.goto(LOGIN_URLS[marketplace])
        input(f"Faca login em {LOGIN_URLS[marketplace]} na janela aberta e aperte Enter aqui... ")
    finally:
        ctx.close()
        pw.stop()


def scrape_url(
    marketplace: str,
    url: str,
    limit: int = 40,
    headless: bool = False,
    details: bool = False,
    scrolls: int = 6,
    ctx=None,
    query: str | None = None,
    parser=None,
    label: str | None = None,
) -> tuple[list[dict], str]:
    """Abre uma URL pronta (busca, categoria, mais vendidos) no navegador e
    devolve (produtos normalizados, caminho dos brutos).

    parser(html, payloads) -> list[dict] substitui o parser padrao do
    marketplace (ML = cards da busca, Shopee/TikTok = JSON interceptado)."""
    own = ctx is None
    if own:
        pw, ctx = open_browser(headless=headless)
    payloads: list = []

    def on_response(resp):
        hints = JSON_HINTS.get(marketplace)
        if not hints or resp.request.resource_type not in ("xhr", "fetch"):
            return
        if not any(h in resp.url for h in hints):
            return
        try:
            payloads.append(resp.json())
        except Exception:
            pass

    try:
        page = ctx.new_page()
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        if any(h in page.url for h in BLOCK_HINTS):
            raise ScrapeBlocked(
                f"{marketplace}: o site pediu verificacao/login ({page.url}). "
                f"Rode: scrape --marketplace {marketplace} --login"
            )
        for _ in range(scrolls):  # rola para carregar mais produtos (lazy load)
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1200)
        html = page.content()
        if parser is not None:
            products = parser(html, payloads)
        elif marketplace == MARKETPLACE_ML:
            products = parse_ml_search(html, query)
        elif marketplace == MARKETPLACE_SHOPEE:
            products = parse_shopee_payloads(payloads, query)
        else:
            products = parse_tiktok_payloads(payloads, query)
        products = products[:limit]
        if details and marketplace == MARKETPLACE_ML:
            for p in products:
                if not p.get("permalink"):
                    continue
                try:
                    page.goto(p["permalink"], wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(1500)
                    extra = parse_ml_item_page(page.content())
                    p.update({k: v for k, v in extra.items() if v is not None})
                except Exception:
                    continue
                time.sleep(1.0)
        raw = _save_raw(marketplace, label or query or url, html, payloads)
        page.close()
        return products, raw
    finally:
        if own:
            ctx.close()
            pw.stop()


def scrape_search(
    marketplace: str,
    query: str,
    limit: int = 40,
    headless: bool = False,
    details: bool = False,
    scrolls: int = 6,
    ctx=None,
) -> tuple[list[dict], str]:
    """Abre a busca no navegador e devolve (produtos normalizados, caminho dos brutos)."""
    return scrape_url(
        marketplace, SEARCH_URLS[marketplace](query), limit=limit, headless=headless,
        details=details, scrolls=scrolls, ctx=ctx, query=query,
    )


def fetch_shopee_category_tree(ctx=None, headless: bool = False) -> tuple[list[dict], str]:
    """Abre SHOPEE_CATEGORY_TREE_URL no navegador logado e parseia a arvore.

    Endpoint interno NAO validado ao vivo. Se vier vazio, confira o JSON salvo
    em data/raw/ e rode `categories --marketplace shopee --file <json>`."""
    own = ctx is None
    if own:
        pw, ctx = open_browser(headless=headless)
    try:
        page = ctx.new_page()
        resp = page.goto(SHOPEE_CATEGORY_TREE_URL, wait_until="domcontentloaded", timeout=60000)
        payload = None
        try:
            payload = resp.json() if resp is not None else None
        except Exception:
            try:
                payload = json.loads(page.inner_text("body"))
            except Exception:
                payload = None
        raw = _save_raw(MARKETPLACE_SHOPEE, "category_tree", None if payload else page.content(), [payload] if payload else [])
        page.close()
        return parse_shopee_category_tree(payload or {}), raw
    finally:
        if own:
            ctx.close()
            pw.stop()


def store_products(session, products: list[dict], source: str, supplier_product_id: int | None = None) -> int:
    """Grava a saida do extrator no banco (anuncios + snapshots + vinculo opcional)."""
    from .collector import add_snapshot, link, upsert_listing

    listing_keys = LISTING_KEYS
    for p in products:
        listing = upsert_listing(session, {k: v for k, v in p.items() if k in listing_keys})
        snap = {k: v for k, v in p.items() if k not in listing_keys}
        extras = {k: snap.pop(k) for k in list(snap) if k in ("sponsored",)}
        snap["extra_data"] = extras or None
        add_snapshot(session, listing, snap, source)
        if supplier_product_id:
            link(session, supplier_product_id, listing)
    return len(products)
