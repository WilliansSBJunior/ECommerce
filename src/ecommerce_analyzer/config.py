import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/ecommerce.db")
ML_SITE_ID = os.getenv("ML_SITE_ID", "MLB")
ML_API_BASE_URL = "https://api.mercadolibre.com"
