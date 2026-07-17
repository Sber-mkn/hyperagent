from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[String] = mapped_column(String(100), unique=True)
    password_hash: Mapped[String] = mapped_column(String(255), unique=False)
    db_port: Mapped[int] = mapped_column(Integer)
    rabbitmq_port: Mapped[int] = mapped_column(Integer)
    rabbitmq_mgmt_port: Mapped[int] = mapped_column(Integer)
