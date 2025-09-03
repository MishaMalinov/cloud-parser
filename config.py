# cloud_parser/config.py

EXCEL_TABLE = "https://docs.google.com/spreadsheets/u/0/d/1_057HZS_eWhiCqBWaj8eO5km0us3CoA4lYkkZImIaDY/htmlview?pli=1#gid=0"
PRODUCTS_PATH = "./products.csv"
OUTPUT_XML = "./products.xml"
OUTPUT_LOG = "./logs.txt"

# Поля CSV (українською)
CSV_COL_NAME = "Назва товару"
CSV_COL_SKU = "Артикул"
CSV_COL_ATTRS = "Характеристика"
CSV_COL_URL = "Посилання"
CSV_COL_PRICE = "Ціна роздрібна з ПДВ в євро"
CSV_COL_PHOTO = "Фото"  # на випадок, якщо з'явиться

# Поля таблиці брендів у Google Sheet (очікуємо 2 колонки: Бренд, Посилання)
SHEET_COL_BRAND = "Бренд"
SHEET_COL_LINK = "Посилання"

# Скільки фото максимум брати з папки (щоб не роздувати XML)
MAX_IMAGES_PER_PRODUCT = 10

# Яке значення availability виводити
DEFAULT_AVAILABILITY = "in_stock"

# Таймаути/ретраї для мережі
HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
