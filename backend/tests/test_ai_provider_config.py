from app.config import Settings


def test_ai_provider_config_accepts_generic_env_names(monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "provider-key")
    monkeypatch.setenv("AI_MODEL", "provider/free-model")
    monkeypatch.setenv("AI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("AI_APP_URL", "https://knowyourmpza.vercel.app")
    monkeypatch.setenv("AI_APP_TITLE", "KnowYourMPZA")

    settings = Settings()

    assert settings.ai_api_key == "provider-key"
    assert settings.ai_model == "provider/free-model"
    assert settings.ai_base_url == "https://openrouter.ai/api/v1"
    assert settings.ai_app_url == "https://knowyourmpza.vercel.app"
    assert settings.ai_app_title == "KnowYourMPZA"


def test_ai_provider_config_keeps_openai_env_names_for_backwards_compatibility(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    settings = Settings()

    assert settings.ai_api_key == "openai-key"
    assert settings.ai_model == "gpt-test"
    assert settings.ai_base_url == "https://api.openai.com/v1"
