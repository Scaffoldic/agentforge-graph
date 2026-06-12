"""Shapes — exercises classes, nested methods, internal + external imports,
a cross-file resolvable call, and an unresolvable attribute call."""

import math

from mathutils import square


class Circle:
    def __init__(self, radius):
        self.radius = radius

    def area(self):
        return math.pi * square(self.radius)  # cross-file call: -> mathutils.square


def describe(shape):
    return shape.area()  # attribute call on a parameter: unresolvable, recorded not guessed
