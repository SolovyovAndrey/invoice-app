import hashlib
from pathlib import Path
from fastapi import UploadFile, HTTPException
from backend.config import config

VALID_SIGNATURES = {
    ".pdf":  [b"%PDF"],
    ".png":  [b"\x89PNG"],
    ".jpg":  [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".tiff": [b"II\x2a\x00", b"MM\x00\x2a"],
}


async def validate_upload(file: UploadFile) -> bytes:
    if not file.filename:
        raise HTTPException(400, "No filename provided")
    ext = Path(file.filename).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(400, "File type not allowed")
    contents = await file.read()
    await file.seek(0)
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > config.MAX_FILE_SIZE_MB:
        raise HTTPException(400, "File too large")
    if len(contents) < 8:
        raise HTTPException(400, "File is empty or too small")
    valid_sigs = VALID_SIGNATURES.get(ext, [])
    if valid_sigs:
        header = contents[:8]
        if not any(header.startswith(sig) for sig in valid_sigs):
            raise HTTPException(400, "File content does not match extension")
    return contents


def compute_file_hash(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()
