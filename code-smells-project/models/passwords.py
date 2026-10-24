import hmac

from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(raw):
    return generate_password_hash(raw)


def verify_password(stored, raw):
    if stored.startswith(("scrypt:", "pbkdf2:")) and stored.count("$") == 2:
        return check_password_hash(stored, raw), False
    return hmac.compare_digest(stored.encode("utf-8"), raw.encode("utf-8")), True
