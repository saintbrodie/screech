from backend.services import TTLValue


def test_ttl_cache_caches_none_values():
    cache = TTLValue(ttl_seconds=60)
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return None

    assert cache.get_or_update(loader) is None
    assert cache.get_or_update(loader) is None
    assert calls == 1
