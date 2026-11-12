"""FastAPI application entry point."""

import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.services.ocr.service import default_ocr_service

app = FastAPI(
    title="Structra Backend",
    version="0.1.0",
    description="Backend foundation for Structra.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(api_router)


@app.on_event("startup")
async def warm_up_local_ocr() -> None:
    """Warm RapidOCR in the background so its cold start does not delay a receipt."""
    asyncio.create_task(default_ocr_service.warmup())
