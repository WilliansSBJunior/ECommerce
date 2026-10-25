"""Tabela de taxas dos marketplaces usada no calculo de lucro.

ATENCAO: as taxas mudam varias vezes por ano. Os valores abaixo sao a
referencia publica de outubro/2026 (fontes em docs/estudo_viabilidade_extrator.md)
e devem ser conferidos na Central do Vendedor de cada plataforma. Para
ajustar sem mexer no codigo, crie o arquivo `data/taxas.json` (caminho em
FEES_OVERRIDE_FILE) com a mesma estrutura de DEFAULT_FEE_TABLES, por exemplo:

{
  "ml": {"classico": {"percent": 0.12, "bands": [[0, 78.99, 6.75]]}}
}

Cada marketplace tem "planos" (ex: ML classico/premium). Cada plano tem:
  percent: comissao percentual sobre o preco de venda (categoria media)
  bands:   lista [preco_min, preco_max, taxa_fixa] -> taxa fixa por unidade
           cobrada quando o preco cai na faixa; fora das faixas = 0. Lacunas
           entre uma faixa e a proxima (ex: 79.99 -> 80) contam na faixa de baixo.
  percent_bands (opcional): lista [preco_min, preco_max, percent] quando a
           comissao percentual tambem varia por faixa de preco (Shopee/TikTok).
"""

import json
import math
import os
from dataclasses import dataclass

from .config import FEES_OVERRIDE_FILE

INF = math.inf

DEFAULT_FEE_TABLES: dict = {
    "ml": {
        "_default_plan": "classico",
        # Comissao varia por categoria (11-14% classico, 15-18% premium). Usamos a
        # media; passe `percent_override` quando souber a taxa da categoria.
        # Custo fixo por unidade em anuncios abaixo de R$79 (envio Flex/proprio;
        # Full/Agencia/Coleta nao pagam desde mar/2026 -> use logistic="full").
        "classico": {
            "percent": 0.13,
            "bands": [[0, 28.99, 6.25], [29, 49.99, 6.50], [50, 78.99, 6.75]],
        },
        "premium": {
            "percent": 0.18,
            "bands": [[0, 28.99, 6.25], [29, 49.99, 6.50], [50, 78.99, 6.75]],
        },
    },
    "shopee": {
        "_default_plan": "padrao",
        # Vendedor CNPJ, vigente out/2026: ate R$79,99 -> 20% + R$4,50;
        # R$80-99,99 -> 14% + R$16; R$100-199,99 -> 14% + R$20; >= R$200 -> 14% + R$26.
        "padrao": {
            "percent": 0.14,
            "percent_bands": [[0, 79.99, 0.20], [80, INF, 0.14]],
            "bands": [[0, 79.99, 4.50], [80, 99.99, 16.0], [100, 199.99, 20.0], [200, INF, 26.0]],
        },
        # Vendedor CPF paga R$3 a mais por item em todas as faixas.
        "cpf": {
            "percent": 0.14,
            "percent_bands": [[0, 79.99, 0.20], [80, INF, 0.14]],
            "bands": [[0, 79.99, 7.50], [80, 99.99, 19.0], [100, 199.99, 23.0], [200, INF, 29.0]],
        },
    },
    "tiktok": {
        "_default_plan": "padrao",
        # Vigente desde 15/jul/2026: abaixo de R$50 -> 10% + R$4; R$50 ou mais -> 6% + R$6.
        # Programa de frete (6%, teto R$50) incluso em `shipping_program_percent`.
        "padrao": {
            "percent": 0.06,
            "percent_bands": [[0, 49.99, 0.10], [50, INF, 0.06]],
            "bands": [[0, 49.99, 4.0], [50, INF, 6.0]],
            "shipping_program_percent": 0.06,
            "shipping_program_cap": 50.0,
        },
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_fee_tables(override_file: str | None = FEES_OVERRIDE_FILE) -> dict:
    tables = DEFAULT_FEE_TABLES
    if override_file and os.path.exists(override_file):
        with open(override_file, encoding="utf-8") as fh:
            tables = _deep_merge(tables, json.load(fh))
    return tables


def _band_value(bands: list, price: float, default: float = 0.0) -> float:
    """Valor da faixa em que `price` cai.

    As tabelas usam intervalos fechados com lacuna de centavo (ex: [0, 79.99] e
    [80, 99.99]). Para nao deixar preco "sem faixa" nessas lacunas, cada faixa
    vale de `low` ate o `low` da proxima (exclusivo); so a ultima respeita o
    proprio `high` (acima dele = default).
    """
    ordered = sorted(
        ((low, INF if high in (None, "inf") else high, value) for low, high, value in bands or []),
        key=lambda b: b[0],
    )
    for i, (low, high, value) in enumerate(ordered):
        if i + 1 < len(ordered):
            if low <= price < ordered[i + 1][0]:
                return value
        elif low <= price <= high:
            return value
    return default


@dataclass
class FeeBreakdown:
    marketplace: str
    plan: str
    price: float
    commission_percent: float
    commission: float
    fixed_fee: float
    shipping_program: float

    @property
    def total(self) -> float:
        return round(self.commission + self.fixed_fee + self.shipping_program, 2)


def marketplace_fee(
    marketplace: str,
    price: float,
    plan: str | None = None,
    percent_override: float | None = None,
    logistic: str | None = None,
    tables: dict | None = None,
) -> FeeBreakdown:
    """Calcula a taxa cobrada pelo marketplace em uma venda ao preco `price`.

    logistic="full" no ML zera o custo fixo (regra desde mar/2026 para
    Full/Agencia/Coleta). percent_override permite usar a comissao exata da
    categoria em vez da media.
    """
    tables = tables or load_fee_tables()
    if marketplace not in tables:
        raise ValueError(f"Marketplace desconhecido para taxas: {marketplace}")
    mk = tables[marketplace]
    plan = plan or mk.get("_default_plan")
    rule = mk[plan]
    # Preco real sempre tem 2 casas: trunca para centavos (79.995 -> 79.99,
    # na faixa de baixo). O round(.., 6) evita ruido de float (59.9*100 = 5989.999..).
    price = math.floor(round(float(price or 0) * 100, 6)) / 100

    percent = rule.get("percent", 0.0)
    if rule.get("percent_bands"):
        percent = _band_value(rule["percent_bands"], price, percent)
    if percent_override is not None:
        percent = percent_override

    fixed = _band_value(rule.get("bands", []), price)
    if marketplace == "ml" and logistic in ("full", "fulfillment", "agencia", "coleta", "xd_drop_off", "cross_docking"):
        fixed = 0.0

    shipping_program = 0.0
    if rule.get("shipping_program_percent"):
        shipping_program = min(price * rule["shipping_program_percent"], rule.get("shipping_program_cap", INF))

    return FeeBreakdown(
        marketplace=marketplace,
        plan=plan,
        price=price,
        commission_percent=percent,
        commission=round(price * percent, 2),
        fixed_fee=round(fixed, 2),
        shipping_program=round(shipping_program, 2),
    )


def breakeven_price(
    marketplace: str,
    unit_costs: float,
    tax_rate: float = 0.0,
    plan: str | None = None,
    percent_override: float | None = None,
    logistic: str | None = None,
    tables: dict | None = None,
) -> float | None:
    """Menor preco de venda em que o lucro por unidade e zero.

    Como a taxa fixa e a comissao mudam por faixa de preco, resolve a equacao
    por busca incremental em centavos (passo de R$0,01, contado em inteiros
    para nao acumular erro de float) -- simples e sem erro de faixa.
    """
    tables = tables or load_fee_tables()
    start_cents = round(max(unit_costs, 1.0) * 100)
    for step in range(200000):  # ate R$2000 acima do custo
        price = (start_cents + step) / 100
        fee = marketplace_fee(marketplace, price, plan, percent_override, logistic, tables)
        profit = price - fee.total - price * tax_rate - unit_costs
        if profit >= 0:
            return price
    return None
