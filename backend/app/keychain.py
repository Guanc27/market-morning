"""macOS Keychain access via the `security` CLI — no extra Python dependency.

Used to store brokerage OAuth tokens (trading scope) in the login Keychain
instead of a plaintext file. Every call is best-effort: if the CLI is missing
(non-macOS) or errors, the helpers return None/False so the caller can degrade
gracefully rather than crash.
"""

from __future__ import annotations

import subprocess

_TIMEOUT = 10


def get_generic_password(service: str, account: str) -> str | None:
    """Return the stored secret for (service, account), or None if absent."""
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    # `-w` prints only the password; strip the single trailing newline it appends.
    secret = proc.stdout
    if secret.endswith("\n"):
        secret = secret[:-1]
    return secret or None


def set_generic_password(service: str, account: str, secret: str) -> bool:
    """Create/overwrite (-U) the secret for (service, account). True on success."""
    try:
        proc = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", secret],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def delete_generic_password(service: str, account: str) -> bool:
    """Delete the secret for (service, account). True if an item was removed."""
    try:
        proc = subprocess.run(
            ["security", "delete-generic-password", "-s", service, "-a", account],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0
