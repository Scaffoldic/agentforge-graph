"""gateway → orders, via an httpx client instance with a base_url
(ENH-020 instance-client + base_url capture)."""

import httpx

orders = httpx.Client(base_url="http://orders")


def list_orders():
    return orders.get("/v1/orders").json()
