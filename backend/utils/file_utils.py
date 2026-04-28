import uuid
import time
from pathlib import Path
from backend.config import config


def save_temp_file(contents: bytes, original_name: str) -> Path:
    ext = Path(original_name).suffix.lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    temp_path = config.TEMP_DIR / unique_name
    temp_path.write_bytes(contents)
    return temp_path


def cleanup_temp_file(file_path: Path) -> None:
    try:
        if file_path.exists():
            file_path.unlink()
    except OSError:
        pass


def cleanup_old_temp_files(max_age_minutes: int = 30) -> int:
    removed = 0
    cutoff = time.time() - (max_age_minutes * 60)
    for f in config.TEMP_DIR.iterdir():
        if f.name == ".gitkeep":
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed
