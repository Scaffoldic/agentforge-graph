// Math helpers — module-level functions and an intra-file call.

export const PI = 3.14159;

export function square(x: number): number {
  return x * x;
}

export function cube(x: number): number {
  return square(x) * x; // intra-file call: cube -> square (resolvable)
}
