"""Vincula automaticamente produtos do fornecedor a anuncios concorrentes.

Metodo: sobreposicao de palavras (tokens) entre os termos de busca do produto
e o titulo do anuncio, ignorando acentos, palavras genericas e unidades. O
score de 0 a 1 e a fracao das palavras do termo que aparecem no titulo, com
bonus se os numeros (ex: "5.3", "2000mah", "128gb") batem. Termos com numero
que nao aparece no titulo sao penalizados - isso evita casar "fone i12" com
"fone i7s", por exemplo.

Nao e perfeito: revise os vinculos no dashboard / `score --details` e use
`unlink-product` para tirar anuncios que nao sao o mesmo produto.
"""

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from .collector import link
from .models import MLListing, SupplierProduct

STOPWORDS = {
    "de", "da", "do", "das", "dos", "e", "com", "para", "pra", "em", "a", "o", "as", "os",
    "um", "uma", "kit", "novo", "nova", "original", "promocao", "oferta", "envio", "imediato",
    "pronta", "entrega", "frete", "gratis", "full", "top", "qualidade", "premium", "unidade",
    "unidades", "un", "pcs", "pecas", "peca", "c", "p", "x", "the", "and", "for", "with",
}
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?[a-z]*")


def tokens(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    raw = re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?[a-z]*", text)
    out = set()
    for tok in raw:
        tok = tok.replace(",", ".")
        if tok in STOPWORDS or len(tok) < 2 and not tok.isdigit():
            continue
        if len(tok) > 4 and tok.endswith("s") and not tok[-2].isdigit():
            tok = tok[:-1]  # plural simples: fones -> fone
        out.add(tok)
    return out


def similarity(term: str, title: str) -> float:
    t_tokens, title_tokens = tokens(term), tokens(title)
    if not t_tokens:
        return 0.0
    hit = len(t_tokens & title_tokens) / len(t_tokens)
    nums = {t for t in t_tokens if any(ch.isdigit() for ch in t)}  # 500ml, i12, 128gb
    if nums:
        num_hit = len(nums & title_tokens) / len(nums)
        hit = hit * (0.5 + 0.5 * num_hit)
    return round(hit, 3)


def match_product(
    session: Session,
    product: SupplierProduct,
    threshold: float = 0.6,
    marketplace: str | None = None,
    candidates: list[MLListing] | None = None,
) -> list[tuple[MLListing, float]]:
    """Vincula `product` aos anuncios com similaridade >= threshold. Retorna os novos vinculos."""
    if candidates is None:
        query = select(MLListing)
        if marketplace:
            query = query.where(MLListing.marketplace == marketplace)
        candidates = session.scalars(query).all()
    linked = []
    terms = product.query_terms() + [product.name]
    for listing in candidates:
        best = max(similarity(t, listing.title) for t in terms)
        if best >= threshold and link(session, product.id, listing, match_score=best):
            linked.append((listing, best))
    return linked


def match_all(session: Session, threshold: float = 0.6, product_id: int | None = None) -> dict[int, int]:
    query = select(SupplierProduct)
    if product_id:
        query = query.where(SupplierProduct.id == product_id)
    candidates = session.scalars(select(MLListing)).all()
    result = {}
    for product in session.scalars(query).all():
        result[product.id] = len(match_product(session, product, threshold, candidates=candidates))
    return result
