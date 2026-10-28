import time
from pathlib import Path

import pytest

from app.core import dev_token
from app.core.auth import AuthError, Role, StaticKey, TokenVerifier

ISS, AUD = "https://idp.example", "risk-api"


@pytest.fixture(scope="module")
def keys(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, str]:
    return dev_token.load_or_create_keys(tmp_path_factory.mktemp("keys"))


def verifier(public: str) -> TokenVerifier:
    return TokenVerifier(ISS, AUD, StaticKey(public))


def test_a_minted_token_is_accepted_by_the_real_verifier(keys: tuple[str, str]) -> None:
    token = dev_token.mint(keys[0], subject="m1", roles=["mentor"], issuer=ISS, audience=AUD)
    principal = verifier(keys[1]).verify(token)
    assert (principal.subject, principal.role) == ("m1", Role.MENTOR)


def test_the_highest_role_wins_when_a_token_has_several(keys: tuple[str, str]) -> None:
    token = dev_token.mint(
        keys[0], subject="x", roles=["faculty", "staff"], issuer=ISS, audience=AUD
    )
    assert verifier(keys[1]).verify(token).role is Role.STAFF


def test_keys_are_created_once_and_reused(tmp_path: Path) -> None:
    first = dev_token.load_or_create_keys(tmp_path / "k")
    assert dev_token.load_or_create_keys(tmp_path / "k") == first
    assert dev_token.load_or_create_keys(tmp_path / "other") != first


def test_a_token_signed_with_another_key_is_refused(keys: tuple[str, str], tmp_path: Path) -> None:
    other_private, _ = dev_token.load_or_create_keys(tmp_path / "other")
    token = dev_token.mint(other_private, subject="m1", roles=["mentor"], issuer=ISS, audience=AUD)
    with pytest.raises(AuthError):
        verifier(keys[1]).verify(token)


def test_an_expired_token_is_refused(keys: tuple[str, str]) -> None:
    token = dev_token.mint(
        keys[0],
        subject="m1",
        roles=["mentor"],
        issuer=ISS,
        audience=AUD,
        ttl_seconds=60,
        now=time.time() - 3600,
    )
    with pytest.raises(AuthError):
        verifier(keys[1]).verify(token)


@pytest.mark.parametrize("ttl", [0, -1, dev_token.MAX_TTL_SECONDS + 1])
def test_the_lifetime_is_bounded(keys: tuple[str, str], ttl: int) -> None:
    with pytest.raises(ValueError):
        dev_token.mint(
            keys[0], subject="m1", roles=["mentor"], issuer=ISS, audience=AUD, ttl_seconds=ttl
        )


def test_a_blank_subject_is_refused(keys: tuple[str, str]) -> None:
    with pytest.raises(ValueError):
        dev_token.mint(keys[0], subject="  ", roles=["mentor"], issuer=ISS, audience=AUD)


def test_the_public_key_line_fits_on_one_line_for_dotenv(keys: tuple[str, str]) -> None:
    line = dev_token.public_key_env_line(keys[1])
    assert line.startswith('JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\\n')
    assert "\n" not in line and "PRIVATE" not in line


def test_it_refuses_to_run_in_production(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_ENV", "production")
    assert dev_token.main(["--role", "admin"]) == 2
    assert "production" in capsys.readouterr().err
    assert not (tmp_path / ".dev-keys").exists()  # and made no key


def test_it_needs_the_issuer_and_audience_to_be_configured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JWT_ISSUER", "")
    monkeypatch.setenv("JWT_AUDIENCE", "")
    assert dev_token.main(["--role", "mentor"]) == 2
    assert "JWT_ISSUER" in capsys.readouterr().err


def test_the_command_prints_a_token_the_verifier_accepts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JWT_ISSUER", ISS)
    monkeypatch.setenv("JWT_AUDIENCE", AUD)
    assert dev_token.main(["--role", "faculty", "--sub", "f1"]) == 0
    token = capsys.readouterr().out.strip()
    public = (tmp_path / ".dev-keys" / "public.pem").read_text()
    principal = verifier(public).verify(token)
    assert (principal.subject, principal.role) == ("f1", Role.FACULTY)
