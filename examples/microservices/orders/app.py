"""orders — a FastAPI service. Exposes `/v1/orders` and charges via payments
(ENH-020: a requests call matched to payments' OpenAPI contract)."""

import requests
from fastapi import FastAPI

app = FastAPI()


@app.get("/v1/orders")
def list_orders():
    return {"orders": [], "charged": _charge()}


@app.get("/v1/orders/{oid}")
def get_order(oid: str):
    return {"id": oid}


def _charge():
    return requests.post("http://payments/v1/charge", json={"amount": 100}).json()
