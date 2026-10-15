from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import conversation, claims, health
from .core.audit import AuditMiddleware
from .core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    get_logger("startup").info("app.starting")
    yield
    get_logger("shutdown").info("app.stopped")


app = FastAPI(
    title="UI Conversational AI",
    description="Weekly unemployment-insurance claim eligibility — agentic conversational interview",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(conversation.router, prefix="/api/conversations", tags=["conversation"])
app.include_router(claims.router, prefix="/api/claims", tags=["claims"])
