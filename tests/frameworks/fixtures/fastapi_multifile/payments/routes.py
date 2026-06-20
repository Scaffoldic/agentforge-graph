"""A router defined in its own module; mounted under a prefix by main.py."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/charge")
def charge() -> dict:
    return {}


@router.post("/refund")
def refund() -> dict:
    return {}
