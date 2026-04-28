from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from backend.config import config
from backend.database import init_db
from backend.routers import upload, history
from backend.utils.file_utils import cleanup_old_temp_files


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    removed = cleanup_old_temp_files(max_age_minutes=0)
    print("Database:", config.DATA_DIR / config.DATABASE_NAME)
    print("Cleaned", removed, "old temp files")
    print("Invoice App ready at http://localhost:8000")
    yield
    cleanup_old_temp_files(max_age_minutes=0)


app = FastAPI(
    title="Swiss Invoice Processor",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(history.router)
app.mount("/static", StaticFiles(directory=str(config.FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_frontend():
    return FileResponse(str(config.FRONTEND_DIR / "index.html"))
