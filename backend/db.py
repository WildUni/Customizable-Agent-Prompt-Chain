from sqlmodel import Session, SQLModel, create_engine

import config

# SQLite needs check_same_thread=False because FastAPI serves requests on
# multiple threads; other databases don't accept this argument.
_connect_args = (
    {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(config.DATABASE_URL, connect_args=_connect_args)

def init_db():
    import models  # noqa: F401  (registers table models with SQLModel.metadata)
    SQLModel.metadata.create_all(engine)   # creates tables from your models

def get_session():
    with Session(engine) as session:
        yield session
