"""The app: mounts the payments router under /api and uses a cross-file DI
provider. Exercises ENH-011 route-prefix composition + DI grounding."""

from fastapi import Depends, FastAPI

from .db import get_db
from .payments import routes

app = FastAPI()
app.include_router(routes.router, prefix="/api")


@app.get("/me")
def me(db: object = Depends(get_db)) -> object:
    return db
