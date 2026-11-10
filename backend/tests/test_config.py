from app.config import Settings


def test_list_settings_accept_csv_and_json(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://kb.example.com")
    monkeypatch.setenv("ALLOWED_EXTENSIONS", '[".pdf", ".md"]')
    s = Settings()
    assert s.cors_origins == ["http://localhost:3000", "https://kb.example.com"]
    assert s.allowed_extensions == [".pdf", ".md"]


def test_default_database_lives_in_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings(data_dir=tmp_path, database_url=None)
    assert s.effective_database_url == f"sqlite:///{tmp_path / 'app.db'}"
