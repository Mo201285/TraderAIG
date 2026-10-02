
import pytest

@pytest.fixture(autouse=True)
def _clear_leverage_cache():
    try:
        from challenge import leverage
        leverage._default_cache.invalidate()
    except Exception:
        pass
    yield
    try:
        from challenge import leverage
        leverage._default_cache.invalidate()
    except Exception:
        pass
