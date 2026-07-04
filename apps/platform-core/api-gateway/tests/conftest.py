import os
import sys
from pathlib import Path

# main.py/deps.py/billing.py use flat imports (`from deps import ...`), which
# only resolve if the api-gateway folder itself is on sys.path -- exactly how
# railway.toml's PYTHONPATH is set up in production. Do the same here so
# `pytest apps/platform-core/api-gateway/tests` works regardless of cwd.
_API_GATEWAY_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_API_GATEWAY_DIR))

# deps.py builds a SQLAlchemy engine from DATABASE_URL at import time (lazy --
# create_engine() doesn't connect until a query runs), and lru_cache()s a
# PyJWKClient off CLERK_JWKS_URL. Tests never hit either for real: get_db and
# get_current_user are always overridden via dependency_overrides. These only
# need to be well-formed enough for import-time construction to not raise.
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/kinetiq_test")
os.environ.setdefault("CLERK_JWKS_URL", "https://example.invalid/.well-known/jwks.json")
