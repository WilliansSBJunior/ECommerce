import pytest

from ecommerce_analyzer.fees import DEFAULT_FEE_TABLES, breakeven_price, marketplace_fee

T = DEFAULT_FEE_TABLES


def test_ml_classico_abaixo_de_79_paga_fixo():
    f = marketplace_fee("ml", 59.90, tables=T)
    assert f.commission == pytest.approx(59.90 * 0.13, abs=0.01)
    assert f.fixed_fee == 6.75


def test_ml_full_nao_paga_fixo():
    assert marketplace_fee("ml", 59.90, logistic="fulfillment", tables=T).fixed_fee == 0


def test_ml_acima_de_79_sem_fixo():
    assert marketplace_fee("ml", 120, tables=T).fixed_fee == 0


@pytest.mark.parametrize(
    "price,pct,fixed",
    [(50, 0.20, 4.50), (85, 0.14, 16.0), (150, 0.14, 20.0), (250, 0.14, 26.0)],
)
def test_shopee_faixas(price, pct, fixed):
    f = marketplace_fee("shopee", price, tables=T)
    assert f.commission_percent == pct and f.fixed_fee == fixed


def test_tiktok_faixas_e_programa_de_frete():
    low, high = marketplace_fee("tiktok", 40, tables=T), marketplace_fee("tiktok", 100, tables=T)
    assert (low.commission_percent, low.fixed_fee) == (0.10, 4.0)
    assert (high.commission_percent, high.fixed_fee) == (0.06, 6.0)
    assert high.shipping_program == 6.0


def test_breakeven_zera_lucro():
    p = breakeven_price("ml", 30, 0.06, tables=T)
    f = marketplace_fee("ml", p, tables=T)
    assert 0 <= p - f.total - p * 0.06 - 30 < 0.2


def test_preco_na_lacuna_entre_faixas_cai_na_faixa_de_baixo():
    # Regressao: 79.995 caia fora de [0, 79.99] e [80, 99.99] -> taxa fixa 0.
    f = marketplace_fee("shopee", 79.995, tables=T)
    assert (f.commission_percent, f.fixed_fee) == (0.20, 4.50)
    assert marketplace_fee("shopee", 79.994, tables=T).fixed_fee == 4.50
    assert marketplace_fee("shopee", 99.995, tables=T).fixed_fee == 16.0


def test_breakeven_shopee_nao_usa_taxa_fixa_zero():
    p = breakeven_price("shopee", 40, 0.06, tables=T)
    f = marketplace_fee("shopee", p, tables=T)
    assert p == round(p, 2)
    assert f.fixed_fee > 0
    assert 0 <= p - f.total - p * 0.06 - 40 < 0.05
