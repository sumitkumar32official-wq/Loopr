import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import Base, engine
from .routers import auth, billing, bookings, core, history, subs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Dev convenience only. Production uses Alembic migrations.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Loopr API", version="0.1.0", lifespan=lifespan)
for r in (auth.router, core.router, subs.router, bookings.router, billing.router, history.router):
    app.include_router(r)


@app.get("/health")
def health():
    return {"ok": True}
