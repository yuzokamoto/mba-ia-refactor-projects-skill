from errors import AuthenticationError, NotFoundError
from models.passwords import hash_password, verify_password
from models.users import LOGIN_FIELDS, serialize_user


class UserService:
    def __init__(self, users):
        self.users = users

    def all(self):
        return self.users.all()

    def require(self, user_id):
        user = self.users.find(user_id)
        if user is None:
            raise NotFoundError("Usuário não encontrado")
        return user

    def create(self, name, email, password):
        return self.users.create(name, email, hash_password(password))

    def login(self, email, password):
        for user in self.users.by_email(email):
            valid, legacy = verify_password(user["senha"], password)
            if valid:
                if legacy:
                    self.users.replace_password(user["id"], user["senha"], hash_password(password))
                return serialize_user(user, LOGIN_FIELDS)
        raise AuthenticationError("Email ou senha inválidos", False)
