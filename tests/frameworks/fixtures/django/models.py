"""Fixture Django app: an abstract base model, a model with a Meta db_table, a
plain model, a model subclassing the abstract base with FK + M2M relations, and
a non-model class (must not be extracted)."""

from django.db import models


class TimestampedModel(models.Model):
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class User(models.Model):
    name = models.CharField(max_length=50)
    email = models.EmailField()

    class Meta:
        db_table = "auth_user"


class Tag(models.Model):
    label = models.CharField(max_length=20)


class Post(TimestampedModel):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    tags = models.ManyToManyField(Tag)


def helper() -> int:
    return 1


class PlainThing:
    x = 1
