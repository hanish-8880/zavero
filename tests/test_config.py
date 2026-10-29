from zavero import config


def test_one_shared_client(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    config.client.cache_clear()
    assert config.client() is config.client()
    config.client.cache_clear()
