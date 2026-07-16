import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

db = os.getenv("ROUTER_DB", "router_db")
user = os.getenv("ROUTER_USER", "router")
password = os.getenv("ROUTER_PASSWORD", "12345")
host = os.getenv("ROUTER_HOST", "router_db")
port = os.getenv("ROUTER_PORT", "5432")
engine = create_engine(
    f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}", echo=False, pool_pre_ping=True
)

Session = sessionmaker(bind=engine, expire_on_commit=False)
