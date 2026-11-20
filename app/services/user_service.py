import re

from sqlalchemy import func

from models import User
from services.errors import ValidationError
from services.security import hash_password, verify_password

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


def normalize_email(email):
    return (email or "").strip().lower()


class UserService:
    def __init__(self, session):
        self.session = session

    def get_user(self, user_id):
        return self.session.get(User, user_id)

    def get_by_email(self, email):
        email = normalize_email(email)
        return self.session.query(User).filter(func.lower(User.email) == email).first()

    def list_users(self):
        return self.session.query(User).order_by(User.email).all()

    @staticmethod
    def _validate_password(password, password_confirm=None):
        if not password or len(password) < MIN_PASSWORD_LENGTH:
            raise ValidationError(f"Heslo musí mít alespoň {MIN_PASSWORD_LENGTH} znaků.")
        if password_confirm is not None and password != password_confirm:
            raise ValidationError("Hesla se neshodují.")

    def create_user(self, email, name, password, password_confirm=None):
        email = normalize_email(email)
        name = (name or "").strip()
        if not EMAIL_RE.match(email):
            raise ValidationError("Zadejte platný e-mail.")
        if not name:
            raise ValidationError("Jméno je povinné.")
        if len(name) > 100:
            raise ValidationError("Jméno může mít nejvýše 100 znaků.")
        self._validate_password(password, password_confirm)
        if self.get_by_email(email):
            raise ValidationError("Uživatel s tímto e-mailem už existuje.")

        user = User(email=email, name=name, password_hash=hash_password(password), is_active=True)
        self.session.add(user)
        self.session.commit()
        return user

    def authenticate(self, email, password):
        user = self.get_by_email(email)
        if user and user.is_active and verify_password(password or "", user.password_hash):
            return user
        return None

    def update_profile(self, user, name):
        name = (name or "").strip()
        if not name:
            raise ValidationError("Jméno je povinné.")
        user.name = name[:100]
        self.session.commit()
        return user

    def change_password(self, user, current_password, new_password, new_password_confirm=None):
        if current_password is not None and not verify_password(current_password, user.password_hash):
            raise ValidationError("Současné heslo není správné.")
        self._validate_password(new_password, new_password_confirm)
        user.password_hash = hash_password(new_password)
        self.session.commit()
