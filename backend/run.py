"""Start Call Center Agent using the host/port from .env:   python run.py"""
import uvicorn

from app.config import settings

if __name__ == "__main__":
    print(f"Customer portal : http://{settings.BACKEND_HOST}:{settings.BACKEND_PORT}/")
    print(f"Admin dashboard : http://{settings.BACKEND_HOST}:{settings.BACKEND_PORT}/admin")
    uvicorn.run("app.main:app", host=settings.BACKEND_HOST, port=settings.BACKEND_PORT)
