import os

from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root (GROQ_API_KEY lives there)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://logistics:logistics@localhost:5433/logistics")
READONLY_DATABASE_URL = os.getenv(
    "READONLY_DATABASE_URL", "postgresql://logistics_ro:readonly_dev@localhost:5433/logistics"
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STUCK_HOURS_THRESHOLD = int(os.getenv("STUCK_HOURS_THRESHOLD", "72"))

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
MAX_SQL_ATTEMPTS = int(os.getenv("MAX_SQL_ATTEMPTS", "2"))


DECISION_MODEL = os.getenv("DECISION_MODEL", GROQ_MODEL)
MAX_TOOL_CALLS = 4


FULFILMENT_WAREHOUSE = os.getenv("FULFILMENT_WAREHOUSE", "Bengaluru")
REPLACEMENT_SHIPPING_INR = 150  # made-up assumption, change freely

COMMUNICATOR_MODEL = os.getenv("COMMUNICATOR_MODEL", GROQ_MODEL)
MAX_CUSTOMER_ASKS = 2   # first email plus one clarification

APPROVAL_THRESHOLD_INR = int(os.getenv("APPROVAL_THRESHOLD_INR", "2000"))

STRUCTURED_OUTPUT_METHOD = os.getenv("STRUCTURED_OUTPUT_METHOD", "")   # "" = library default (function_calling)
PACE_SECONDS = float(os.getenv("PACE_SECONDS", "0"))