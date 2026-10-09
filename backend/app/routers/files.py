from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter()

# Base directory of the project (project root)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

@router.get("/files/{file_path:path}")
async def serve_project_file(file_path: str):
    """Serve any file from the project directory.
    For security reasons this endpoint should be used only in development or behind authentication.
    """
    target = PROJECT_ROOT / file_path
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=target)
