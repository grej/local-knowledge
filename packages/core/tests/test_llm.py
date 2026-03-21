from unittest.mock import MagicMock, patch

from localknowledge.llm import LLMConfig, complete, is_available, llm_status


def test_llm_config_defaults():
    config = LLMConfig()
    assert config.provider == "local"
    assert config.local_model == "mlx-community/Qwen3.5-4B-MLX-4bit"
    assert config.local_server_url == "http://127.0.0.1:8090"
    assert config.auto_start is True
    assert config.startup_timeout_sec == 120


@patch("localknowledge.llm.httpx.get")
def test_is_available_returns_true_on_200(mock_get):
    config = LLMConfig()
    mock_get.return_value = MagicMock(status_code=200)
    assert is_available(config) is True


@patch("localknowledge.llm.httpx.get", side_effect=Exception("connection refused"))
def test_is_available_returns_false_on_error(mock_get):
    config = LLMConfig()
    assert is_available(config) is False


@patch("localknowledge.llm.httpx.post")
def test_complete_returns_content(mock_post):
    config = LLMConfig()
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"choices": [{"message": {"content": "Hello!"}}]},
        raise_for_status=lambda: None,
    )
    result = complete([{"role": "user", "content": "Say hello"}], config)
    assert result == "Hello!"
    call_kwargs = mock_post.call_args
    assert "v1/chat/completions" in call_kwargs.args[0]


@patch("localknowledge.llm.is_available", return_value=False)
def test_llm_status_stopped(mock_avail):
    config = LLMConfig()
    status = llm_status(config)
    assert status["available"] is False
    assert status["provider"] == "local"
    assert status["status"] == "stopped"


@patch("localknowledge.llm.is_available", return_value=True)
def test_llm_status_cloud_available(mock_avail):
    config = LLMConfig()
    config.provider = "openai"
    config.api_key = "sk-test"
    status = llm_status(config)
    assert status["available"] is True
    assert status["provider"] == "openai"
    assert status["status"] == "available"
