"""Tests never inherit a developer's live model opt-in."""
import pytest


@pytest.fixture(autouse=True)
def disable_live_model_environment(monkeypatch):
    monkeypatch.delenv('ENABLE_GEMINI', raising=False)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
