from app import cache


def test_jitter_within_bounds():
    base_ttl = 600
    for _ in range(50):
        val = cache.jitter(base_ttl)
        assert 540 <= val <= 660


def test_cache_miss_and_hit():
    key = "test:item:1"
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return {"id": 1, "name": "Penguin #1"}

    # 1st call: MISS, loads from loader and caches
    data, status = cache.get_or_load(key, loader, ttl=300)
    assert status == "MISS"
    assert data["name"] == "Penguin #1"
    assert calls == 1

    # 2nd call: HIT, returns from Redis cache without calling loader
    data2, status2 = cache.get_or_load(key, loader, ttl=300)
    assert status2 == "HIT"
    assert data2["name"] == "Penguin #1"
    assert calls == 1


def test_null_caching():
    key = "test:not_found"
    calls = 0

    def empty_loader():
        nonlocal calls
        calls += 1
        return None

    # 1st call: returns None, caches null marker
    data, status = cache.get_or_load(key, empty_loader, ttl=300)
    assert data is None
    assert status == "MISS"
    assert calls == 1

    # 2nd call: hits null cache, does not trigger loader
    data2, status2 = cache.get_or_load(key, empty_loader, ttl=300)
    assert data2 is None
    assert status2 == "HIT"
    assert calls == 1


def test_distributed_mutex_lock():
    lock_key = "lock:rebuild:pudgypenguins"
    # Acquire lock
    assert cache.acquire_lock(lock_key, expire=10) is True
    # Second acquisition fails (lock held)
    assert cache.acquire_lock(lock_key, expire=10) is False
    # Release lock
    cache.release_lock(lock_key)
    # Re-acquire succeeds
    assert cache.acquire_lock(lock_key, expire=10) is True
    cache.release_lock(lock_key)


def test_clear_prefix():
    cache.rds.set("user:1", "a")
    cache.rds.set("user:2", "b")
    cache.rds.set("order:1", "c")

    deleted = cache.clear_prefix("user:")
    assert deleted == 2
    assert cache.rds.get("user:1") is None
    assert cache.rds.get("user:2") is None
    assert cache.rds.get("order:1") == "c"
