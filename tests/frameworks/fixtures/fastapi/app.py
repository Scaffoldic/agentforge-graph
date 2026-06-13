from fastapi import APIRouter, FastAPI
from service import charge

app = FastAPI()
router = APIRouter()

PREFIX = "/v1"


@app.get("/health")
def health():
    return {"ok": True}


@router.post("/payments/{pid}/refund")
def refund(pid: str):
    return charge(pid)  # cross-file call: framework + symbol graph coexist


@app.get(PREFIX + "/dynamic")  # non-literal path → counted as unresolved
def dynamic():
    return 1


@app.middleware("http")  # not an HTTP route method → ignored, not counted
def mw():
    return None
