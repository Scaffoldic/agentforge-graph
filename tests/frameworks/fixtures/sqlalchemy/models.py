"""Fixture SQLAlchemy app: classic + 2.0-style declarative models, plus a
relationship (RELATES_TO, deferred) and a plain non-model class (must not be
extracted)."""

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(50))
    posts = relationship("Post", back_populates="author")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    author_id = Column(Integer, ForeignKey("users.id"))


def helper() -> int:
    return 1


class PlainThing:
    x = 1
