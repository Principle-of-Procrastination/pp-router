from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from pprouter import api
from pprouter.router_engine import build_router
from pprouter.routing import DifficultyRouter

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    router = build_router()
    app.state.router = router
    app.state.difficulty = DifficultyRouter(router)
    yield


app = FastAPI(title="pp-router", version="0.1.0", lifespan=lifespan)
app.include_router(api.router)
