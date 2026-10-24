"""Cliente da API oficial do Mercado Livre.

Referencia: https://developers.mercadolivre.com.br/

Desde 2025 a API responde HTTP 403 a chamadas sem token, inclusive busca e
detalhe de anuncios publicos. Este cliente obtem o token sozinho a partir das
credenciais do `.env`, nesta ordem:
  1. token em cache valido (data/ml_token.json);
  2. ML_REFRESH_TOKEN -> grant_type=refresh_token (renova a cada 6h);
  3. ML_CLIENT_ID + ML_CLIENT_SECRET -> grant_type=client_credentials;
  4. ML_ACCESS_TOKEN fixo (expira em 6h, util para teste rapido).
"""

import json
import os
import time

import requests

from . import config

SEARCH_PAGE_SIZE = 50
MULTIGET_SIZE = 20  # /items?ids= aceita ate 20 ids por chamada


class MLAuthError(RuntimeError):
    """Falta token/credencial ou a API recusou o acesso."""


_token_cache: dict = {}


def _load_cached_token() -> dict | None:
    if _token_cache.get("access_token") and _token_cache.get("expires_at", 0) > time.time() + 60:
        return _token_cache
    path = config.ML_TOKEN_CACHE_FILE
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("access_token") and data.get("expires_at", 0) > time.time() + 60:
                _token_cache.update(data)
                return data
        except (OSError, ValueError):
            pass
    return None


def _save_token(payload: dict) -> dict:
    data = {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + int(payload.get("expires_in", 21600)),
    }
    _token_cache.clear()
    _token_cache.update(data)
    path = config.ML_TOKEN_CACHE_FILE
    if path:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    return data


def _request_token(form: dict) -> dict:
    resp = requests.post(
        f"{config.ML_API_BASE_URL}/oauth/token",
        data=form,
        headers={"accept": "application/json", "content-type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise MLAuthError(f"Falha ao obter token do ML ({resp.status_code}): {resp.text[:300]}")
    return _save_token(resp.json())


def get_access_token(force_refresh: bool = False) -> str:
    if not force_refresh:
        cached = _load_cached_token()
        if cached:
            return cached["access_token"]
    refresh = (_token_cache.get("refresh_token") if _token_cache else None) or config.ML_REFRESH_TOKEN
    if config.ML_CLIENT_ID and config.ML_CLIENT_SECRET:
        if refresh:
            return _request_token(
                {
                    "grant_type": "refresh_token",
                    "client_id": config.ML_CLIENT_ID,
                    "client_secret": config.ML_CLIENT_SECRET,
                    "refresh_token": refresh,
                }
            )["access_token"]
        return _request_token(
            {
                "grant_type": "client_credentials",
                "client_id": config.ML_CLIENT_ID,
                "client_secret": config.ML_CLIENT_SECRET,
            }
        )["access_token"]
    if config.ML_ACCESS_TOKEN:
        return config.ML_ACCESS_TOKEN
    raise MLAuthError(
        "A API do Mercado Livre exige token. Preencha ML_CLIENT_ID e ML_CLIENT_SECRET "
        "no .env (crie um app gratis em https://developers.mercadolivre.com.br/devcenter). "
        "Passo a passo: docs/estudo_viabilidade_extrator.md, secao 'Token da API do ML'."
    )


def exchange_code(code: str) -> dict:
    """Troca o `code` do fluxo authorization_code por access+refresh token."""
    if not (config.ML_CLIENT_ID and config.ML_CLIENT_SECRET):
        raise MLAuthError("Preencha ML_CLIENT_ID e ML_CLIENT_SECRET no .env antes.")
    return _request_token(
        {
            "grant_type": "authorization_code",
            "client_id": config.ML_CLIENT_ID,
            "client_secret": config.ML_CLIENT_SECRET,
            "code": code,
            "redirect_uri": config.ML_REDIRECT_URI,
        }
    )


def authorization_url() -> str:
    return (
        "https://auth.mercadolivre.com.br/authorization?response_type=code"
        f"&client_id={config.ML_CLIENT_ID}&redirect_uri={config.ML_REDIRECT_URI}"
    )


def _get(path: str, params: dict | None = None) -> dict | list:
    url = f"{config.ML_API_BASE_URL}{path}"
    for attempt in range(2):
        token = get_access_token(force_refresh=attempt > 0)
        resp = requests.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if resp.status_code == 401 and attempt == 0:
            continue  # token expirou: renova uma vez
        if resp.status_code == 429:
            time.sleep(2)
            continue
        if resp.status_code in (401, 403):
            raise MLAuthError(
                f"API do ML recusou o acesso a {path} ({resp.status_code}): {resp.text[:300]}"
            )
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return resp.json()


def search_items(
    query: str | None = None,
    site_id: str | None = None,
    max_results: int = 200,
    category: str | None = None,
    sort: str | None = None,
) -> list[dict]:
    """Busca anuncios por termo e/ou categoria. Cada item recebe `_position` (1 = topo)."""
    site_id = site_id or config.ML_SITE_ID
    items: list[dict] = []
    offset = 0
    while len(items) < max_results:
        limit = min(SEARCH_PAGE_SIZE, max_results - len(items))
        params = {"limit": limit, "offset": offset}
        if query:
            params["q"] = query
        if category:
            params["category"] = category
        if sort:
            params["sort"] = sort
        payload = _get(f"/sites/{site_id}/search", params)
        page_items = payload.get("results", [])
        if not page_items:
            break
        for i, it in enumerate(page_items):
            it["_position"] = offset + i + 1
        items.extend(page_items)
        offset += len(page_items)
        if offset >= payload.get("paging", {}).get("total", 0):
            break
    return items[:max_results]


def get_item_details(item_id: str) -> dict:
    return _get(f"/items/{item_id}")


def get_items_details_bulk(item_ids: list[str], delay_seconds: float = 0.0) -> dict[str, dict]:
    """Detalhe em lote via /items?ids= (20 por chamada). Ignora ids com erro."""
    details: dict[str, dict] = {}
    for start in range(0, len(item_ids), MULTIGET_SIZE):
        chunk = item_ids[start : start + MULTIGET_SIZE]
        try:
            payload = _get("/items", {"ids": ",".join(chunk)})
        except requests.HTTPError:
            continue
        for entry in payload or []:
            body = entry.get("body") or {}
            if entry.get("code") == 200 and body.get("id"):
                details[body["id"]] = body
        if delay_seconds:
            time.sleep(delay_seconds)
    return details


def get_category_highlights(category_id: str, site_id: str | None = None) -> list[dict]:
    """Mais vendidos da categoria: lista de {id, position, type: ITEM|PRODUCT|USER_PRODUCT}."""
    site_id = site_id or config.ML_SITE_ID
    payload = _get(f"/highlights/{site_id}/category/{category_id}")
    return payload.get("content", []) if isinstance(payload, dict) else []


def get_product_items(product_id: str) -> list[dict]:
    """Anuncios (vendedores) que competem dentro de um produto de catalogo."""
    payload = _get(f"/products/{product_id}/items")
    return payload.get("results", []) if isinstance(payload, dict) else []


def get_trends(category_id: str | None = None, site_id: str | None = None) -> list[dict]:
    site_id = site_id or config.ML_SITE_ID
    path = f"/trends/{site_id}/{category_id}" if category_id else f"/trends/{site_id}"
    payload = _get(path)
    return payload if isinstance(payload, list) else []


def get_category(category_id: str) -> dict:
    return _get(f"/categories/{category_id}")
