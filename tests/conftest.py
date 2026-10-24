import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("FEES_OVERRIDE_FILE", "")

import pytest  # noqa: E402

from ecommerce_analyzer import db  # noqa: E402


@pytest.fixture
def session(tmp_path):
    db.configure(f"sqlite:///{tmp_path}/t.db")
    db.init_db()
    with db.get_session() as s:
        yield s
