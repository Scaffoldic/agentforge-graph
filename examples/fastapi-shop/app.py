"""A tiny FastAPI + SQLAlchemy shop — sample code to index with agentforge-graph.

Index it and explore the framework graph:

    ckg index examples/fastapi-shop
    ckg routes        # the endpoints + handlers
    ckg models        # User / Order with their relations
    ckg services      # get_db injected into the handlers
"""

from fastapi import Depends, FastAPI
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base, relationship

app = FastAPI()
Base = declarative_base()


def get_db():
    """A dependency provider — becomes a Service injected into the handlers."""
    return {"session": "..."}


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(50))
    email = Column(String(120))
    orders = relationship("Order", back_populates="user")  # RELATES_TO Order


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    total_cents = Column(Integer)
    user_id = Column(Integer, ForeignKey("users.id"))       # RELATES_TO User (fk)
    user = relationship("User", back_populates="orders")


@app.get("/users/{uid}")
def get_user(uid: int, db=Depends(get_db)):                 # noqa: B008
    return {"id": uid}


@app.post("/users/{uid}/orders")
def create_order(uid: int, total_cents: int, db=Depends(get_db)):  # noqa: B008
    return {"user_id": uid, "total_cents": total_cents}
