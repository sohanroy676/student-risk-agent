"""DEV ONLY: mint access tokens for trying the API and web app locally.

    python -m app.core.dev_token --role mentor --sub m1
    python -m app.core.dev_token --show-public-key      # the JWT_PUBLIC_KEY line for .env

The signing key is created on first use in `.dev-keys/` (git-ignored). Set JWT_ISSUER and
JWT_AUDIENCE in `.env`, put the printed public key in JWT_PUBLIC_KEY, and the API accepts the
tokens. Never use that public key anywhere real: whoever holds the private key can sign in as
anyone, so this tool refuses to run when APP_ENV is production.
"""

import argparse
import sys
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.settings import get_settings

KEY_DIR = Path(".dev-keys")
ROLES = ("admin", "staff", "mentor", "faculty", "student", "parent")
MAX_TTL_SECONDS = 24 * 3600


def load_or_create_keys(folder: Path = KEY_DIR) -> tuple[str, str]:
    """The (private, public) PEM pair stored in `folder`, created if it is not there yet."""
    private_path, public_path = folder / "private.pem", folder / "public.pem"
    if private_path.exists() and public_path.exists():
        return private_path.read_text(), public_path.read_text()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    folder.mkdir(parents=True, exist_ok=True)
    private_path.write_text(private)
    private_path.chmod(0o600)
    public_path.write_text(public)
    return private, public


def mint(
    private_pem: str,
    *,
    subject: str,
    roles: list[str],
    issuer: str,
    audience: str,
    ttl_seconds: int = 3600,
    now: float | None = None,
) -> str:
    if not subject.strip() or not 0 < ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError("a token needs a subject and a lifetime of up to 24 hours")
    issued = int(now if now is not None else time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": issued,
        "exp": issued + ttl_seconds,
        "roles": roles,
    }
    return jwt.encode(claims, private_pem, algorithm="RS256")


def public_key_env_line(public_pem: str) -> str:
    return 'JWT_PUBLIC_KEY="' + public_pem.strip().replace("\n", "\\n") + '"'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DEV ONLY: mint a local access token.")
    parser.add_argument("--role", action="append", choices=ROLES, default=[])
    parser.add_argument("--sub", default="dev-user")
    parser.add_argument("--ttl", type=int, default=3600, help="lifetime in seconds (max 86400)")
    parser.add_argument("--show-public-key", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    if settings.app_env.lower() in ("prod", "production"):
        print("refusing to run: APP_ENV is production", file=sys.stderr)
        return 2
    private, public = load_or_create_keys()
    if args.show_public_key:
        print(public_key_env_line(public))
        return 0
    if not settings.jwt_issuer or not settings.jwt_audience:
        print("set JWT_ISSUER and JWT_AUDIENCE in .env first", file=sys.stderr)
        return 2
    print(
        mint(
            private,
            subject=args.sub,
            roles=args.role or ["mentor"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            ttl_seconds=args.ttl,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
