import base64
import hashlib
import hmac
import secrets

# Doporučení OWASP pro PBKDF2-HMAC-SHA256
ITERATIONS = 600_000
_ALGORITHM = "pbkdf2_sha256"


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def hash_password(password, iterations=None):
    iterations = iterations or ITERATIONS
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_ALGORITHM}${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password, stored_hash):
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored_hash.split("$")
        if algorithm != _ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(digest, expected)
    except (ValueError, AttributeError):
        return False
