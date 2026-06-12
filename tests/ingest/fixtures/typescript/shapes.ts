// Shapes — a class with nested methods, internal + external imports,
// a cross-file resolvable call, and an unresolvable attribute call.

import { square } from "./mathutils";

export class Circle {
  radius: number;

  constructor(radius: number) {
    this.radius = radius;
  }

  area(): number {
    return Math.PI * square(this.radius); // cross-file call: -> mathutils.square
  }
}

export function describe(shape: Circle): number {
  return shape.area(); // attribute call on a parameter: unresolvable, recorded not guessed
}
