from cryptography.fernet import Fernet

class SessionCipher:
    def __init__(self, key: str):
        self.fernet = Fernet(key.encode() if isinstance(key, str) else key)
    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode()).decode()
    def decrypt(self, value: str) -> str:
        return self.fernet.decrypt(value.encode()).decode()
