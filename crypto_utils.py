import hashlib
import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

_key = os.environ.get('TOKEN_ENC_KEY')
if not _key:
    raise RuntimeError(
        "TOKEN_ENC_KEY not set. Generate one with: "
        "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
        "and put it in .env"
    )

_fernet = Fernet(_key.encode() if isinstance(_key, str) else _key)


def encrypt_token(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()


def hash_bearer(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
