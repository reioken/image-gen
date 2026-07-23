from product_image_batch.core.config import AppConfig, load_config


def test_load_config_has_all_providers():
    cfg = load_config()
    for name in ["openai", "google", "bfl", "stability", "fal", "replicate",
                 "ideogram", "recraft", "leonardo", "freepik", "mock"]:
        assert name in cfg.providers


def test_openai_defaults_are_tier_safe():
    cfg = load_config()
    assert cfg.provider("openai").max_concurrent == 2
    assert cfg.provider("openai").rate_limit_per_minute == 5


def test_stability_rate_window():
    cfg = load_config()
    spec = cfg.provider("stability").rate_per_second()
    assert spec == (120.0, 10.0)  # under the documented 150/10s


def test_resolve_model_prefers_default():
    cfg = load_config()
    assert cfg.provider("openai").resolve_model(None) == "gpt-image-2"
    assert cfg.provider("openai").resolve_model("gpt-image-1.5") == "gpt-image-1.5"


def test_has_api_key_reads_env():
    cfg = load_config()
    assert cfg.has_api_key("mock") is True  # mock never needs a key
    assert cfg.has_api_key("openai", env={}) is False
    assert cfg.has_api_key("openai", env={"OPENAI_API_KEY": "sk-x"}) is True


def test_apply_settings_overlay():
    cfg = load_config()
    cfg.apply_settings({
        "global_max_concurrent": 50,
        "per_provider_concurrency": {"openai": 7},
        "enabled_providers": {"fal": True},
        "auto_retry": False,
    })
    assert cfg.global_max_concurrent == 50
    assert cfg.provider("openai").max_concurrent == 7
    assert cfg.provider("fal").enabled is True
    assert cfg.retry.max_retries == 0
