// Shapes — a class with nested methods, an internal import,
// a cross-file resolvable call, and an unresolvable attribute call.

import { square } from "./mathutils";

export class Circle {
  constructor(radius) {
    this.radius = radius;
  }

  area() {
    return Math.PI * square(this.radius); // cross-file call: -> mathutils.square
  }
}

export function describe(shape) {
  return shape.area(); // attribute call on a parameter: unresolvable, recorded not guessed
}
