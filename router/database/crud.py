from sqlalchemy import select

from router.database.session import Session
from router.database.users import User


def add_user(login, password_hash, db_port, rabbitmq_port, rabbitmq_mgmt_port):
    user = User(
        login=login,
        password_hash=password_hash,
        db_port=db_port,
        rabbitmq_port=rabbitmq_port,
        rabbitmq_mgmt_port=rabbitmq_mgmt_port,
    )
    with Session() as session:
        try:
            session.add(user)
        except Exception:
            session.rollback()
            raise
        else:
            session.commit()


def get_user(login):
    with Session() as session:
        user = session.scalar(select(User).where(User.login == login))
        return user
