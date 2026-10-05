from fastapi import Depends, FastAPI

from .api import auth, files, merges, review
from .deps import require_role

app = FastAPI(title="Dedup Platform API", version="0.1.0")

app.include_router(auth.router, prefix="/api/v1")
app.include_router(
    files.router, prefix="/api/v1", dependencies=[Depends(require_role("admin"))]
)
app.include_router(
    merges.router, prefix="/api/v1", dependencies=[Depends(require_role("admin"))]
)
app.include_router(
    review.router, prefix="/api/v1", dependencies=[Depends(require_role("admin", "reviewer"))]
)


@app.get("/health")
def health():
    return {"status": "ok"}