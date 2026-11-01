from contextlib import asynccontextmanager
import logging
import re
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.api.routes.health import router as health_router
from app.api.routes.matches import router as matches_router
from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_var
from app.db.session import engine

configure_logging()
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="Dota 2 Draft Monitor API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def log_http_request(request: Request, call_next):
    supplied_id = request.headers.get("x-request-id", "")
    request_id = supplied_id if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", supplied_id) else str(uuid4())
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        logging.getLogger("backend.http").info(
            "event=http_request_completed method=%s path=%s status=%d duration_ms=%.2f",
            request.method, request.url.path, response.status_code, duration_ms,
        )
        return response
    except Exception:
        logging.getLogger("backend.http").exception(
            "event=http_request_failed method=%s path=%s", request.method, request.url.path
        )
        raise
    finally:
        request_id_var.reset(token)
app.include_router(health_router, prefix="/api/v1")
app.include_router(matches_router, prefix="/api/v1")


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_, exc: SQLAlchemyError) -> JSONResponse:
    logging.getLogger(__name__).exception("Database request failed", exc_info=exc)
    if isinstance(exc, OperationalError):
        status_code = 503
        code = "database_unavailable"
        message = "Database unavailable."
    else:
        status_code = 500
        code = "database_error"
        message = "A database error occurred."
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "error": {
                "code": f"http_{exc.status_code}",
                "message": str(exc.detail),
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(_, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"location": error["loc"], "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request parameters are invalid.",
                "details": errors,
            }
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).exception("Unhandled request error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "An internal error occurred."}},
    )
