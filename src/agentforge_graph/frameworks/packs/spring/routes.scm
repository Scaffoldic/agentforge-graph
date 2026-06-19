; Spring MVC controllers (feat-011). Capture every class; the pack inspects each
; class's annotations (is it a @RestController/@Controller, what is its base
; @RequestMapping path?) and its methods' mapping annotations in code, so the
; path/method derivation and the controller guard stay precise.
(class_declaration
  name: (identifier) @class) @decl
