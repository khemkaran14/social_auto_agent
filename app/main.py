from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api.routes import auth, niches, posts, schedules, social_accounts, users
from app.config import get_settings
from app.database import Base, SessionLocal, engine

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.dev_auto_create_tables:
        # Convenience for local dev. In production, run `alembic upgrade head` instead
        # and set DEV_AUTO_CREATE_TABLES=false.
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Social Auto Agent", version="0.2.0", lifespan=lifespan)

app.include_router(users.router)
app.include_router(auth.router)
app.include_router(social_accounts.router)
app.include_router(niches.router)
app.include_router(schedules.router)
app.include_router(posts.router)


@app.get("/health")
def health() -> dict:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    finally:
        db.close()
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}
