from attest_cloud.ops import TokenBucket


def test_token_bucket_refills():
    b = TokenBucket(rate_per_min=60, burst=2)
    assert b.allow("k", now=0.0)[0] and b.allow("k", now=0.0)[0]
    ok, retry = b.allow("k", now=0.0)
    assert not ok and 0 < retry <= 1.0
    assert b.allow("k", now=1.1)[0]  # one token per second
    assert b.allow("other", now=0.0)[0]


def test_rate_limit_middleware(client, keys):
    bucket = client.app.state.rate_bucket
    bucket.reset()
    bucket.rate, bucket.burst = 0.0, 2
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {keys['agent']}"}).status_code == 200
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {keys['agent']}"}).status_code == 200
    r = client.get("/v1/me", headers={"Authorization": f"Bearer {keys['agent']}"})
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {keys['admin']}"}).status_code == 200  # other key
    bucket.reset()
    bucket.rate, bucket.burst = 10.0, 100.0
