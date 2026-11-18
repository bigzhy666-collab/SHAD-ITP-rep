import pytest


@pytest.fixture(autouse=True)
def isolate_local_storage(tmp_path, monkeypatch):
    # No test may read or write a developer's real station/dataset database.
    monkeypatch.setenv("SHAD_DATA_DIR", str(tmp_path / "service-data"))
