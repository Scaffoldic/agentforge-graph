from fastapi import APIRouter, Depends, FastAPI
from service import charge

app = FastAPI()
router = APIRouter()

PREFIX = "/v1"


def get_db():
    return {"conn": True}


@app.get("/health")
def health():
    return {"ok": True}


@router.post("/payments/{pid}/refund")
def refund(pid: str, db=Depends(get_db)):  # noqa: B008 — FastAPI DI idiom (fixture)
    return charge(pid)  # cross-file call: framework + symbol graph coexist


@app.get(PREFIX + "/dynamic")  # non-literal path → counted as unresolved
def dynamic():
    return 1


@app.middleware("http")  # not an HTTP route method → ignored, not counted
def mw():
    return None
