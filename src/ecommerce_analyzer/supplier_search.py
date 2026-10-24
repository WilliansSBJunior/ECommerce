"""Busca de produtos no site do fornecedor (garimpo reverso).

Fluxo: a partir do titulo de um anuncio mais vendido, monta um termo de busca
(`query_from_title`), abre a busca do site do fornecedor (`Supplier.search_url`
com "{q}" no lugar do termo) e le os resultados (`parse_supplier_results`).

Cada site de atacadista tem um layout diferente, entao o parser tenta, nesta
ordem: (a) seletores CSS informados no cadastro (`Supplier.selectors`);
(b) dados estruturados JSON-LD (Product / ItemList), que muitas lojas
publicam para o Google; (c) heuristica generica: blocos com preco "R$" e um
unico link de produto. A heuristica pode errar; se vier lixo ou vazio,
cadastre seletores com `supplier-site --selectors '{...}'`.

Muitos atacadistas so mostram preco logado: use `supplier-login` uma vez para
salvar a sessao no perfil do navegador (mesmo perfil do extrator).

`parse_supplier_results` e `query_from_title` sao puras (teste offline).
"""

import json
import os
import re
import unicodedata
from datetime import datetime
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup

from . import config
from .matcher import STOPWORDS
from .suppliers_import import parse_money

# Palavras de marketing/logistica que nao ajudam a achar o produto no fornecedor.
QUERY_STOPWORDS = STOPWORDS | {
    "sem", "fio", "envio", "imediato", "imediata", "lancamento", "lancamentos", "brinde",
    "brindes", "garantia", "nf", "nfe", "nota", "fiscal", "lacrado", "lacrada", "barato",
    "promo", "liquidacao", "queima", "estoque", "oficial", "melhor", "preco", "mais",
    "vendido", "vendidos", "sucesso", "viral", "atacado", "revenda", "ate", "ao", "no",
    "na", "nos", "nas", "por", "seu", "sua",
}
REMOVE_PHRASES = ("sem fio", "pronta entrega", "envio imediato", "frete gratis", "nota fiscal")

WORD_RE = re.compile(r"[0-9A-Za-zÀ-ÿ]+(?:[.,\-/][0-9A-Za-zÀ-ÿ]+)*")
PRICE_RE = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)")
INSTALLMENT_RE = re.compile(r"\d+\s*x\s*(?:de\s*)?$", re.I)
SKU_RE = re.compile(r"\b(?:sku|c[oó]d(?:igo)?|ref(?:er[eê]ncia)?)\.?\s*:?\s*([A-Z0-9][\w\-.]{2,})", re.I)
OLD_PRICE_TAGS = ("s", "del", "strike")
MIN_LINK_TEXT = 10
MAX_ANCESTORS = 5


def _norm_word(word: str) -> str:
    return unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode().lower()


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def query_from_title(title: str, max_words: int = 6) -> str:
    """Termo de busca a partir do titulo do anuncio.

    Mantem a ordem das palavras, tira stopwords e palavras de marketing,
    remove duplicatas e preserva codigos de modelo (i12, 500ml, 20w, usb-c).
    Ex: "Fone De Ouvido Bluetooth I12 TWS Sem Fio Envio Imediato" ->
    "fone ouvido bluetooth i12 tws"."""
    raw = WORD_RE.findall((title or "").lower())
    keys = [_norm_word(w) for w in raw]
    drop = set()
    for phrase in REMOVE_PHRASES:  # frases inteiras ("sem fio") antes das palavras soltas
        parts = phrase.split()
        for i in range(len(keys) - len(parts) + 1):
            if keys[i : i + len(parts)] == parts:
                drop.update(range(i, i + len(parts)))
    words, seen = [], set()
    for i, (word, key) in enumerate(zip(raw, keys)):
        if i in drop or key in QUERY_STOPWORDS or (len(key) < 2 and not key.isdigit()):
            continue
        base = key[:-1] if len(key) > 4 and key.endswith("s") and not key[-2].isdigit() else key
        if base in seen:
            continue
        seen.add(base)
        words.append(word)
        if len(words) >= max_words:
            break
    return " ".join(words)


def _price_from_text(text: str) -> float | None:
    """Preco de venda num texto com possivelmente "De R$ X por R$ Y" e parcelas.
    Ignora parcelas ("3x de R$ 10,00"); prefere o valor depois de "por"."""
    candidates = []
    for m in PRICE_RE.finditer(text or ""):
        before = text[max(0, m.start() - 12): m.start()]
        if INSTALLMENT_RE.search(before.strip()):
            continue
        candidates.append((m, before))
    if not candidates:
        return None
    for m, before in candidates:
        if re.search(r"por\s*:?\s*$", before, re.I):
            return parse_money(m.group(1))
    return parse_money(candidates[0][0].group(1))


def _text_without_old_price(node) -> str:
    parts = []
    for string in node.find_all(string=True):
        if string.find_parent(OLD_PRICE_TAGS) is not None or string.find_parent(["script", "style"]) is not None:
            continue
        parts.append(str(string))
    return _clean(" ".join(parts))


def _link_text(a) -> str:
    return _clean(a.get_text(" ")) or _clean(a.get("title")) or ""


def _result(title, price, url, sku, base_url) -> dict:
    return {
        "title": _clean(title),
        "price": price,
        "url": urljoin(base_url, url) if url else None,
        "sku": _clean(str(sku)) if sku not in (None, "") else None,
    }


def _parse_with_selectors(soup, base_url: str, selectors: dict) -> list[dict]:
    results, seen = [], set()
    for item in soup.select(selectors.get("item") or "__nada__"):
        title_node = item.select_one(selectors["title"]) if selectors.get("title") else None
        link_node = item.select_one(selectors["link"]) if selectors.get("link") else None
        if link_node is None:
            link_node = title_node if (title_node is not None and title_node.name == "a") else item.select_one("a[href]")
        title = _link_text(title_node) if title_node is not None else (_link_text(link_node) if link_node else "")
        if not title:
            continue
        price_node = item.select_one(selectors["price"]) if selectors.get("price") else None
        price = _price_from_text(_text_without_old_price(price_node)) if price_node is not None else None
        if price is None and price_node is not None:
            price = parse_money(_clean(price_node.get_text()))
        if price is None:
            price = _price_from_text(_text_without_old_price(item))
        href = link_node.get("href") if link_node is not None else None
        sku_node = item.select_one(selectors["sku"]) if selectors.get("sku") else None
        sku = _clean(sku_node.get_text()) if sku_node is not None else None
        key = href or title
        if key in seen:
            continue
        seen.add(key)
        results.append(_result(title, price, href, sku, base_url))
    return results


def _is_type(d: dict, name: str) -> bool:
    t = d.get("@type")
    return t == name or (isinstance(t, list) and name in t)


def _offer_price(offers) -> float | None:
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if not isinstance(offers, dict):
        return None
    for key in ("price", "lowPrice", "highPrice"):
        if offers.get(key) not in (None, ""):
            return parse_money(offers[key])
    spec = offers.get("priceSpecification")
    if isinstance(spec, dict) and spec.get("price") is not None:
        return parse_money(spec["price"])
    return None


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _parse_json_ld(soup, base_url: str) -> list[dict]:
    results, seen = [], set()
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except ValueError:
            continue
        for d in _walk(data):
            if _is_type(d, "Product") and d.get("name"):
                url = d.get("url") or ((d.get("offers") or {}).get("url") if isinstance(d.get("offers"), dict) else None)
                row = _result(d["name"], _offer_price(d.get("offers")), url, d.get("sku") or d.get("mpn"), base_url)
            elif _is_type(d, "ListItem") and d.get("name") and d.get("url") and not isinstance(d.get("item"), dict):
                row = _result(d["name"], None, d["url"], None, base_url)
            else:
                continue
            key = row["url"] or row["title"]
            if key in seen:
                continue
            seen.add(key)
            results.append(row)
    return results


def _parse_heuristic(soup, base_url: str) -> list[dict]:
    results, seen = [], set()
    for string in soup.find_all(string=re.compile(r"R\$")):
        node = string.parent
        if node is None or string.find_parent(["script", "style", "head"] + list(OLD_PRICE_TAGS)) is not None:
            continue
        # "R$" e o numero podem estar em spans separados: sobe ate ter o valor
        for _ in range(2):
            if PRICE_RE.search(_clean(node.get_text(" "))) or node.parent is None:
                break
            node = node.parent
        container = None
        for _ in range(MAX_ANCESTORS + 1):
            links = {}
            for a in node.find_all("a", href=True):
                if len(_link_text(a)) >= MIN_LINK_TEXT:
                    links.setdefault(a["href"], a)
            if len(links) == 1:
                container = (node, next(iter(links.values())))
                break
            if len(links) > 1 or node.parent is None or node.name in ("body", "html"):
                break  # bloco grande demais (lista inteira) ou chegou no topo
            node = node.parent
        if container is None:
            continue
        box, a = container
        href = a["href"]
        if href in seen:
            continue
        seen.add(href)
        text = _text_without_old_price(box)
        sku = SKU_RE.search(text)
        results.append(_result(_link_text(a), _price_from_text(text), href, sku.group(1) if sku else None, base_url))
    return results


def parse_supplier_results(html: str, base_url: str, selectors: dict | None = None) -> list[dict]:
    """Le a pagina de resultados da busca do fornecedor -> [{title, price, url, sku}].

    Ordem: seletores informados; JSON-LD Product/ItemList; heuristica de blocos
    com preco R$ e um unico link de texto >= 10 caracteres. Links relativos sao
    resolvidos com base_url; resultados repetidos (mesmo link) sao removidos."""
    soup = BeautifulSoup(html or "", "html.parser")
    if selectors and selectors.get("item"):
        found = _parse_with_selectors(soup, base_url, selectors)
        if found:
            return found
    found = _parse_json_ld(soup, base_url)
    if found:
        return found
    return _parse_heuristic(soup, base_url)


# --------------------------------------------------------------------------
# Parte com rede/navegador (so roda na maquina do usuario)
# --------------------------------------------------------------------------

def build_search_url(search_url: str, query: str) -> str:
    if "{q}" not in (search_url or ""):
        raise ValueError("search_url precisa ter {q} no lugar do termo, ex: https://site.com/busca?q={q}")
    return search_url.replace("{q}", quote_plus(query))


def site_home(search_url: str) -> str:
    u = urlparse(search_url)
    return f"{u.scheme}://{u.netloc}/"


def _selectors_of(supplier) -> dict | None:
    sel = supplier.selectors
    if isinstance(sel, str):
        try:
            sel = json.loads(sel)
        except ValueError:
            sel = None
    return sel if isinstance(sel, dict) else None


def _save_raw(supplier, query: str, html: str) -> str:
    from .scraper import slugify

    os.makedirs(config.RAW_CAPTURE_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(config.RAW_CAPTURE_DIR, f"fornecedor{supplier.id}_{slugify(query)[:40]}_{stamp}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html or "")
    return path


def search_supplier(supplier, query: str, ctx=None, use_browser: bool = True, headless: bool = False) -> list[dict]:
    """Busca `query` no site do fornecedor e devolve [{title, price, url, sku}].

    Com navegador (padrao) usa o perfil logado (open_browser); sem navegador
    (`use_browser=False`) faz um GET simples, que so funciona em site estatico.
    O HTML bruto fica em data/raw/fornecedor<id>_<termo>_<data>.html."""
    url = build_search_url(supplier.search_url, query)
    if not use_browser:
        import requests

        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9",
        })
        resp.raise_for_status()
        html = resp.text
    else:
        from .scraper import open_browser

        own = ctx is None
        if own:
            pw, ctx = open_browser(headless=headless)
        try:
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            for _ in range(2):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(800)
            html = page.content()
            page.close()
        finally:
            if own:
                ctx.close()
                pw.stop()
    _save_raw(supplier, query, html)
    return parse_supplier_results(html, url, _selectors_of(supplier))


def login_supplier(supplier) -> None:
    """Abre o site do fornecedor no perfil do navegador para o usuario logar."""
    from .scraper import open_browser

    home = site_home(supplier.search_url) if supplier.search_url else None
    if not home:
        raise ValueError(f"Fornecedor {supplier.id} sem search_url. Rode supplier-site antes.")
    pw, ctx = open_browser(headless=False)
    try:
        page = ctx.new_page()
        page.goto(home)
        input(f"Faca login em {home} na janela aberta e aperte Enter aqui... ")
    finally:
        ctx.close()
        pw.stop()
