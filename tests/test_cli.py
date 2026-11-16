import sys
from pathlib import Path
import pytest
from envyy import cli


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Runs each test inside a clean temporary directory with a sample env.yaml."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "env.yaml").write_text(
        """_meta:
  stages:
    - dev
    - prod
  populate: dev
  consts:
    PORT: 5432
environment:
  APP_ENV:
    dev: development
    prod: production
  DB_PORT:
    dev: "${PORT}"
    prod: "${PORT}"
""",
        encoding="utf-8",
    )
    return tmp_path


def test_gen_default_writes_dot_env(workspace: Path) -> None:
    assert cli.run_pipeline("dev", stub=False) is True

    env_file = workspace / ".env"
    assert env_file.is_file()
    content = env_file.read_text(encoding="utf-8")
    assert "APP_ENV=development" in content
    assert "DB_PORT=5432" in content
    assert not (workspace / ".env.dev").exists()


def test_gen_stub_writes_stage_file_without_overwriting_dot_env(
    workspace: Path,
) -> None:
    # Seed an active .env for dev
    assert cli.run_pipeline("dev", stub=False) is True
    dev_content = (workspace / ".env").read_text(encoding="utf-8")

    # Generate a stub for prod
    assert cli.run_pipeline("prod", stub=True) is True

    stub_file = workspace / ".env.prod"
    assert stub_file.is_file()
    prod_content = stub_file.read_text(encoding="utf-8")
    assert "APP_ENV=production" in prod_content
    assert "DB_PORT=5432" in prod_content

    # Original .env must remain untouched
    assert (workspace / ".env").read_text(encoding="utf-8") == dev_content


def test_cli_gen_stub_flag(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["envy", "gen", "prod", "-s"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert (workspace / ".env.prod").is_file()
    assert not (workspace / ".env").exists()


def test_rejects_undeclared_stage_and_namespace_collision(workspace: Path) -> None:
    # Requesting an undeclared stage fails before writing .env
    assert cli.run_pipeline("staging") is False
    assert not (workspace / ".env").exists()

    # Undeclared key inside a variable block triggers a namespace collision error
    (workspace / "env.yaml").write_text(
        """_meta:
  stages:
    - dev
  populate: dev
environment:
  APP_ENV:
    dev: development
    staging: staging
""",
        encoding="utf-8",
    )
    assert cli.run_pipeline("dev") is False


def test_enforces_upper_snake_case_consts(workspace: Path) -> None:
    # Hyphenated or lowercase constant names in _meta.consts are rejected
    (workspace / "env.yaml").write_text(
        """_meta:
  stages:
    - dev
  populate: dev
  consts:
    authn-service-env: development
environment:
  APP_ENV:
    dev: "${authn-service-env}"
""",
        encoding="utf-8",
    )
    assert cli.run_pipeline("dev") is False

    # Invalid ${...} reference format in environment values is rejected
    (workspace / "env.yaml").write_text(
        """_meta:
  stages:
    - dev
  populate: dev
  consts:
    VALID_CONST: development
environment:
  APP_ENV:
    dev: "${bad-ref}"
""",
        encoding="utf-8",
    )
    assert cli.run_pipeline("dev") is False


def test_rejects_legacy_top_level_keys(workspace: Path) -> None:
    (workspace / "env.yaml").write_text(
        """populate: dev
localvars:
  PORT: 5432
environment:
  DB_PORT:
    dev: "${PORT}"
""",
        encoding="utf-8",
    )
    assert cli.run_pipeline("dev") is False
