from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pprouter import api
from pprouter.config import HISTORY_PATH
from pprouter.history import HistoryStore
from pprouter.router_engine import build_router
from pprouter.routing import DifficultyRouter

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    router = build_router()
    app.state.router = router
    app.state.difficulty = DifficultyRouter(router)
    app.state.history = HistoryStore(Path(HISTORY_PATH))
    yield


app = FastAPI(title="pp-router", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api.router)
