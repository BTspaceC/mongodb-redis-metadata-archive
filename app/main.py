from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import admin, rank, stats, tokens

app = FastAPI(
    title="NFT Archive & Rarity Analytics Engine",
    description="High-performance metadata archive, statistical rarity scoring engine and real-time analytics API for Pudgy Penguins and Azuki NFTs.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for decoupled frontend or cross-origin client apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers
app.include_router(tokens.router)
app.include_router(rank.router)
app.include_router(stats.router)
app.include_router(admin.router)


@app.get("/api/health", tags=["system"])
def health_check():
    """System health check endpoint for monitoring and uptime probes."""
    return {"status": "ok", "service": "nft-archive-engine", "version": "1.0.0"}


# Mount static web directory
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class NoCacheStaticFiles(StaticFiles):
    """Static file handler with no-cache header to prevent stale browser caching."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


if WEB_DIR.exists():
    app.mount("/", NoCacheStaticFiles(directory=WEB_DIR, html=True), name="web")
