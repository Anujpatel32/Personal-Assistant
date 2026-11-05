import pytest
from config.settings import Settings, settings
from config.defaults import DEFAULT_WAKE_WORD, DEFAULT_SELECTED_MODEL

def test_settings_singleton():
    s1 = Settings()
    s2 = Settings()
    assert s1 is s2
    assert s1 is settings

def test_defaults_loaded():
    assert settings.wake_word == DEFAULT_WAKE_WORD
    assert settings.selected_model in ["gemini", "llama", "groq", "nvidia", "openrouter"]

def test_to_dict_keys():
    data = settings.to_dict()
    assert "wake_word" in data
    assert "selected_model" in data
    assert "db_path" in data
    assert "data_dir" in data

def test_paths_exist_or_valid():
    assert settings.base_dir.exists()
    assert settings.base_dir.is_dir()

