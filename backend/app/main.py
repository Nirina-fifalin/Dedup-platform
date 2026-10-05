from fastapi import FastAPI

from .api import files, review

app = FastAPI(title="Dedup Platform API", version="0.1.0")
app.include_router(files.router, prefix="/api/v1")
app.include_router(review.router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}

