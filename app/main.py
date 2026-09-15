from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import auth, niches, posts, schedules, social_accounts, users
from app.config import get_settings
from app.database import Base, engine
from app.scheduler import scheduler

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.dev_auto_create_tables:
        # Convenience for local dev. In production, run `alembic upgrade head` instead
        # and set DEV_AUTO_CREATE_TABLES=false.
        Base.metadata.create_all(bind=engine)

    scheduler.start()
    scheduler.sync_from_db()
    yield
    scheduler.shutdown()


app = FastAPI(title="Social Auto Agent", version="0.1.0", lifespan=lifespan)

app.include_router(users.router)
app.include_router(auth.router)
app.include_router(social_accounts.router)
app.include_router(niches.router)
app.include_router(schedules.router)
app.include_router(posts.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
