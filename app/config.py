import os
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://logistics:logistics@localhost:5433/logistics")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STUCK_HOURS_THRESHOLD = int(os.getenv("STUCK_HOURS_THRESHOLD", "72"))