; NestJS controllers (feat-011). Capture every class; the pack inspects each
; class's decorators (`@Controller('base')`) and its methods' decorators
; (`@Get(':id')` …) in code, since TypeScript decorators are preceding siblings
; of the node they annotate (not children) — so ordered traversal stays precise.
(class_declaration
  name: (type_identifier) @class) @decl
