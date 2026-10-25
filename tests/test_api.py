def test_health_check(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["service"] == "nft-archive-engine"


def test_list_collections(client, sample_tokens):
    resp = client.get("/api/collections")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["_id"] == "pudgypenguins"


def test_list_tokens(client, sample_tokens):
    resp = client.get("/api/tokens?collection=pudgypenguins")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["token_id"] in [1, 2]


def test_get_single_token(client, sample_tokens):
    # 1st request: Cache Miss
    resp = client.get("/api/tokens/pudgypenguins/1")
    assert resp.status_code == 200
    assert resp.headers.get("X-Cache") == "MISS"
    data = resp.json()
    assert data["name"] == "Pudgy Penguin #1"

    # 2nd request: Cache Hit
    resp2 = client.get("/api/tokens/pudgypenguins/1")
    assert resp2.status_code == 200
    assert resp2.headers.get("X-Cache") == "HIT"


def test_get_nonexistent_token_404(client):
    resp = client.get("/api/tokens/pudgypenguins/999999")
    assert resp.status_code == 404
