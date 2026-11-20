import pytest


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path_factory, monkeypatch):
    # Los recientes (y la configuración futura) nunca se escriben en el %APPDATA% real.
    monkeypatch.setenv("PSTUDIO_CONFIG_DIR", str(tmp_path_factory.mktemp("config")))
