import logging
import subprocess

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.limiter import limiter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Reservations API",
    description="API REST per a la gestió de reserves, franges horàries i tipus de sessió.",
    version="1.0.0",
)

# CORS — permet tots els orígens per facilitar integració amb frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info("%s %s", request.method, request.url.path)
    response = await call_next(request)
    logger.info("%s %s → %s", request.method, request.url.path, response.status_code)
    return response


@app.on_event("startup")
async def startup():
    """Executa les migracions d'Alembic automàticament a l'arrencada."""
    logger.info("Running Alembic migrations...")
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("Alembic migration failed: %s", result.stderr)
        raise RuntimeError(f"Alembic migration failed: {result.stderr}")
    logger.info("Alembic migrations completed successfully.")


# Register routers
from app.routers import session_types, slots, reservations, auth  # noqa: E402

app.include_router(auth.router)
app.include_router(session_types.router)
app.include_router(slots.router)
app.include_router(reservations.router)


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "message": "Reservations API is running"}
