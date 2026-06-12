"""Math helpers — exercises module-level functions and an intra-file call."""

PI = 3.14159


def square(x):
    return x * x


def cube(x):
    return square(x) * x  # intra-file call: cube -> square (resolvable)
