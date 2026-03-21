from localknowledge.config import Config


def test_defaults(base_dir):
    config = Config.load(base_dir)
    assert config.llm.provider == "local"
    assert config.tts.voice == "af_sky"
    assert config.database.path == "store.db"
    assert config.embeddings.model == "BAAI/bge-small-en-v1.5"


def test_set_value(base_dir):
    config = Config.load(base_dir)
    config.set_value("llm.provider", "openai")
    config.set_value("tts.speed", "1.5")
    reloaded = Config.load(base_dir)
    assert reloaded.llm.provider == "openai"
    assert reloaded.tts.speed == 1.5


def test_toml_roundtrip(base_dir):
    config = Config.load(base_dir)
    config.llm.provider = "anthropic"
    config.llm.api_key = "sk-test-123"
    config.save()
    reloaded = Config.load(base_dir)
    assert reloaded.llm.provider == "anthropic"
    assert reloaded.llm.api_key == "sk-test-123"


def test_product_sections(base_dir):
    config = Config.load(base_dir)
    config.set_product_config(
        "readcast", {"output_dir": "~/.readcast/output", "auto_listen": True}
    )
    reloaded = Config.load(base_dir)
    rc = reloaded.product_config("readcast")
    assert rc["output_dir"] == "~/.readcast/output"
    assert rc["auto_listen"] is True
