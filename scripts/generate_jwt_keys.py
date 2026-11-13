from __future__ import annotations

import argparse
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    argparse.ArgumentParser(
        description="Generate a local RS256 key pair without overwriting existing keys."
    ).parse_args()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is unavailable; choose a protected user-only directory.")
    key_directory = Path(local_app_data) / "RecruitmentManagementSystem" / "keys"
    key_directory.mkdir(parents=True, exist_ok=True)
    private_path = key_directory / "jwt-private.pem"
    public_path = key_directory / "jwt-public.pem"
    if private_path.exists() or public_path.exists():
        raise FileExistsError(
            "JWT key files already exist. Refusing to overwrite existing credentials."
        )

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_bytes = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    try:
        with private_path.open("xb") as private_file:
            private_file.write(private_bytes)
        with public_path.open("xb") as public_file:
            public_file.write(public_bytes)
    except OSError:
        private_path.unlink(missing_ok=True)
        public_path.unlink(missing_ok=True)
        raise
    if os.name == "posix":
        private_path.chmod(0o600)
        public_path.chmod(0o644)

    print(f"Private key path: {private_path}")
    print(f"Public key path:  {public_path}")
    print("Set JWT_PRIVATE_KEY_PATH and JWT_PUBLIC_KEY_PATH in your local environment.")
    print("Keep the private key user-restricted and out of source control.")


if __name__ == "__main__":
    main()
