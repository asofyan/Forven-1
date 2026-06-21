

def test_bootstrap_copies_default_env_when_missing(monkeypatch, tmp_path):
    home = tmp_path / "forven"
    monkeypatch.setenv("FORVEN_HOME", str(home))
    default_env = tmp_path / "default.env"
    default_env.write_text("FORVEN_ENV=beta\n")
    monkeypatch.setenv("FORVEN_DEFAULT_ENV", str(default_env))
    from forven.config import ensure_state_dir_bootstrapped
    ensure_state_dir_bootstrapped()
    assert (home / ".env").read_text() == "FORVEN_ENV=beta\n"


def test_bootstrap_leaves_existing_env_alone(monkeypatch, tmp_path):
    home = tmp_path / "forven"
    home.mkdir()
    (home / ".env").write_text("FORVEN_ENV=custom\n")
    monkeypatch.setenv("FORVEN_HOME", str(home))
    default_env = tmp_path / "default.env"
    default_env.write_text("FORVEN_ENV=beta\n")
    monkeypatch.setenv("FORVEN_DEFAULT_ENV", str(default_env))
    from forven.config import ensure_state_dir_bootstrapped
    ensure_state_dir_bootstrapped()
    assert (home / ".env").read_text() == "FORVEN_ENV=custom\n"
