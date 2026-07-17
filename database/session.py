import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.tables import Base

db = os.getenv("POSTGRES_DB", "hyperagent_db")
user = os.getenv("POSTGRES_USER", "supervisor")
password = os.getenv("POSTGRES_PASSWORD", "12345")
host = os.getenv("POSTGRES_HOST", "agent_db")
port = os.getenv("POSTGRES_PORT", "5432")
engine = create_engine(
    f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}", echo=False, pool_pre_ping=True
)

Base.metadata.create_all(bind=engine)

Session = sessionmaker(bind=engine, expire_on_commit=False)
