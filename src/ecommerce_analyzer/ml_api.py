"""Cliente simples para a API publica do Mercado Livre.

Referencia: https://developers.mercadolivre.com.br/
Nao requer autenticacao para busca e detalhe de itens publicos.
"""

import time

import requests

from .config import ML_API_BASE_URL, ML_SITE_ID

SEARCH_PAGE_SIZE = 50


def search_items(query: str, site_id: str = ML_SITE_ID, max_results: int = 200) -> list[dict]:
    """Busca anuncios por termo. Retorna a lista de resumos de itens da API de busca."""
    items: list[dict] = []
    offset = 0
    while len(items) < max_results:
        limit = min(SEARCH_PAGE_SIZE, max_results - len(items))
        resp = requests.get(
            f"{ML_API_BASE_URL}/sites/{site_id}/search",
            params={"q": query, "limit": limit, "offset": offset},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        page_items = payload.get("results", [])
        if not page_items:
            break
        items.extend(page_items)
        offset += len(page_items)
        total = payload.get("paging", {}).get("total", 0)
        if offset >= total:
            break
    return items[:max_results]


def get_item_details(item_id: str) -> dict:
    """Detalhe completo de um item (inclui sold_quantity, que a busca nao traz)."""
    resp = requests.get(f"{ML_API_BASE_URL}/items/{item_id}", timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_items_details_bulk(item_ids: list[str], delay_seconds: float = 0.0) -> dict[str, dict]:
    """Busca detalhe item a item. A API do ML tambem aceita ?ids= em lote (ate 20 por vez),
    mas fazer um a um aqui evita lidar com respostas parciais/erros mistos."""
    details: dict[str, dict] = {}
    for item_id in item_ids:
        try:
            details[item_id] = get_item_details(item_id)
        except requests.HTTPError:
            continue
        if delay_seconds:
            time.sleep(delay_seconds)
    return details
