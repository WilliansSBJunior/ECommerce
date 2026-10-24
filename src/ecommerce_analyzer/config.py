import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/ecommerce.db")
ML_SITE_ID = os.getenv("ML_SITE_ID", "MLB")
ML_API_BASE_URL = "https://api.mercadolibre.com"

# --- Autenticacao na API do Mercado Livre -------------------------------------
# Desde 2025 a API do ML exige token mesmo para busca e detalhe de anuncios
# publicos (sem token: HTTP 403 "forbidden"). Crie um aplicativo gratis em
# https://developers.mercadolivre.com.br/ e preencha pelo menos CLIENT_ID e
# CLIENT_SECRET. Veja docs/estudo_viabilidade_extrator.md para o passo a passo.
ML_CLIENT_ID = os.getenv("ML_CLIENT_ID")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
ML_ACCESS_TOKEN = os.getenv("ML_ACCESS_TOKEN")  # opcional: token ja gerado (dura 6h)
ML_REFRESH_TOKEN = os.getenv("ML_REFRESH_TOKEN")  # opcional: renova o token sozinho
ML_REDIRECT_URI = os.getenv("ML_REDIRECT_URI", "https://localhost/callback")
ML_TOKEN_CACHE_FILE = os.getenv("ML_TOKEN_CACHE_FILE", "data/ml_token.json")

# --- Custos do vendedor usados no calculo de lucro -----------------------------
# Imposto sobre o faturamento (ex: Simples Nacional ~6% = 0.06). Pode ser
# sobrescrito por produto na tabela de fornecedores (coluna "imposto").
DEFAULT_TAX_RATE = float(os.getenv("DEFAULT_TAX_RATE", "0.06"))
# Custo de embalagem/insumos por unidade, se nao informado por produto.
DEFAULT_PACKAGING_COST = float(os.getenv("DEFAULT_PACKAGING_COST", "1.50"))
# Arquivo JSON opcional para sobrescrever a tabela de taxas dos marketplaces
# (as taxas mudam com frequencia). Formato: veja fees.py.
FEES_OVERRIDE_FILE = os.getenv("FEES_OVERRIDE_FILE", "data/taxas.json")

# --- Extrator via navegador (Playwright) --------------------------------------
# Pasta onde fica o perfil do navegador com o seu login (ML/Shopee/TikTok).
BROWSER_PROFILE_DIR = os.getenv("BROWSER_PROFILE_DIR", "data/browser_profile")
# Pasta onde o extrator guarda HTML/JSON brutos para depuracao.
RAW_CAPTURE_DIR = os.getenv("RAW_CAPTURE_DIR", "data/raw")
