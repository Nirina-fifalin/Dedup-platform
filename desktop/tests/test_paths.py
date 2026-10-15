import paths


def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DEDUP_DATA_DIR", str(tmp_path))
    assert paths.data_dir() == tmp_path


def test_frozen_app_uses_local_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv("DEDUP_DATA_DIR", raising=False)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.data_dir() == tmp_path / paths.APP_NAME


def test_development_data_lives_outside_the_project(monkeypatch, tmp_path):
    monkeypatch.delenv("DEDUP_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.data_dir() == tmp_path / (paths.APP_NAME + "-dev")
