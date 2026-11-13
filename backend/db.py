from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = "sqlite:///./app.db"   # later: read this from .env

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite-only setting FastAPI needs
)

def init_db():
    import models  # noqa: F401  (registers table models with SQLModel.metadata)
    SQLModel.metadata.create_all(engine)   # creates tables from your models

def get_session():
    with Session(engine) as session:
        yield session