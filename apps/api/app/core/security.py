import hashlib
import secrets


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    password_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=2**14,
        r=8,
        p=1,
    ).hex()
    return f"{salt}${password_hash}"


def verify_password(password: str, stored_password_hash: str) -> bool:
    try:
        salt, password_hash = stored_password_hash.split("$", 1)
    except ValueError:
        return False

    check_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=2**14,
        r=8,
        p=1,
    ).hex()

    return secrets.compare_digest(check_hash, password_hash)