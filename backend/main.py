"""
main.py — FastAPI application entry point

This is the main entry point for the C code review backend service.
It initializes the FastAPI app, includes all routers, and sets up
lifecycle events for Redis connection and parser warming.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as api_router
from github_utils.webhook import router as webhook_router
from cache.redis import redis_client, init_redis
import logging
from fastapi.responses import RedirectResponse
from mangum import Mangum

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    - Startup: Initialize Redis connection, warm up parser
    - Shutdown: Clean up resources
    """
    # Startup
    await init_redis()
    
    # Warm up tree-sitter parser by parsing a minimal C file
    from core.parser import extract_file_ast
    _ = extract_file_ast("int main() { return 0; }")
    
    yield
    
    # Shutdown - Redis client doesn't need explicit cleanup (HTTP-based)


app = FastAPI(
    title="C Code Review API",
    description="Intelligent C code review with AST analysis and LLM insights",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://c-code-review-v2.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(api_router, prefix="/api")
app.include_router(webhook_router, prefix="")


@app.get("/health")
async def health_check():
    """Health check endpoint for load balancers and monitoring."""
    return {"status": "healthy", "service": "c-code-review"}

@app.get("/")
async def root():
    # Redirect to health check or documentation
    return RedirectResponse(url="/health")

handler = Mangum(app)