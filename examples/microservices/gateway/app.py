"""gateway — a FastAPI edge service. Exposes `/` and proxies to orders."""

from fastapi import FastAPI

from .client import list_orders

app = FastAPI()


@app.get("/")
def root():
    return {"service": "gateway", "orders": list_orders()}
