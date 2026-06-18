; JavaScript structure queries (feat-002, pack-js).
; Mirrors the TS pack; the only grammar delta is the class name node:
; JS `class_declaration` names are (identifier), not (type_identifier).
; Definitions may be wrapped in `export_statement`; queries match nested.

; --- definitions ---
(class_declaration
  name: (identifier) @name) @def.class

; --- inheritance (INHERITS): `class B extends A` (JS heritage holds the
; superclass expression directly, no extends_clause wrapper). ---
(class_declaration
  (class_heritage (identifier) @base.name)) @base.def

(function_declaration
  name: (identifier) @name) @def.function

; methods live in a class_body -> promoted to METHOD by the extractor
(method_definition
  name: (property_identifier) @name) @def.function

; --- value bindings (ENH-008, shared with TS) ---
; `const f = (…) => …` / `const f = function () {}` -> Function (named from the
; binding). Captured at any depth — these are genuine functions. (JS has no
; interface/enum/type-alias, so those TS captures are absent here.)
(lexical_declaration
  (variable_declarator
    name: (identifier) @name
    value: [(arrow_function) (function_expression)])) @def.function

; module-level const data tables -> Variable. Scoped to the top level (program /
; export) so locals don't inflate it. Only object/array initializers — NOT call
; results: `const x = require(...)` is an import binding (BUG-006), not a symbol.
(program
  (lexical_declaration
    (variable_declarator
      name: (identifier) @name
      value: [(object) (array)])) @def.variable)
(program
  (export_statement
    (lexical_declaration
      (variable_declarator
        name: (identifier) @name
        value: [(object) (array)])) @def.variable))

; --- imports (ESM) ---
; `import { a, b } from "./mod"` -> module (relative path) + bound names
(import_statement
  (import_clause (named_imports (import_specifier name: (identifier) @import.name)))
  source: (string (string_fragment) @import.module)) @import

; --- imports (CommonJS require, BUG-006) ---
; `const x = require("./mod")` -> module + the default-bound local name
(variable_declarator
  name: (identifier) @import.default
  value: (call_expression
    function: (identifier) @_require
    arguments: (arguments (string (string_fragment) @import.module)))
  (#eq? @_require "require")) @import

; `const { a, b } = require("./mod")` -> module + named bindings
(variable_declarator
  name: (object_pattern (shorthand_property_identifier_pattern) @import.name)
  value: (call_expression
    function: (identifier) @_require
    arguments: (arguments (string (string_fragment) @import.module)))
  (#eq? @_require "require")) @import

; --- exports (CommonJS, BUG-006) ---
; `module.exports = name` (incl. chained `exports = module.exports = name`) ->
; the module's default export, so a default require binds to this symbol.
(assignment_expression
  left: (member_expression
    object: (identifier) @_mod
    property: (property_identifier) @_exp)
  right: (identifier) @export.default
  (#eq? @_mod "module")
  (#eq? @_exp "exports")) @export

; `module.exports = function name() {}` (named function-expression default export —
; the express-style router-factory pattern, incl. chained `var p = module.exports =
; function name(){}`; BUG-006 residual). Two patterns on the same assignment: the
; first makes the function a Function symbol, the second marks it the module default
; export — so `const r = require("./m"); r()` resolves to it. (Anonymous
; `module.exports = function(){}` / `= () => {}` have no name → no symbol; the
; IMPORTS edge still exists.)
(assignment_expression
  left: (member_expression
    object: (identifier) @_mod
    property: (property_identifier) @_exp)
  right: (function_expression
    name: (identifier) @name) @def.function
  (#eq? @_mod "module")
  (#eq? @_exp "exports"))

(assignment_expression
  left: (member_expression
    object: (identifier) @_mod
    property: (property_identifier) @_exp)
  right: (function_expression
    name: (identifier) @export.default)
  (#eq? @_mod "module")
  (#eq? @_exp "exports")) @export

; --- export-member modeling (BUG-006 residual) ---
; Assigned-property exports whose value is an *anonymous* function — these never
; become symbols any other way, so `m.foo()` / `const { foo } = require(...)` /
; direct calls have nothing to bind to. The property name is the export name (an
; anonymous function has no name of its own). Named function-expression values are
; covered by the `const f = function name(){}` value-binding pattern's sibling
; forms; here we deliberately name from the property, which is the export name.

; `exports.foo = function () {}` / `exports.foo = () => {}` -> Function `foo`
(assignment_expression
  left: (member_expression
    object: (identifier) @_obj
    property: (property_identifier) @name)
  right: [(function_expression) (arrow_function)] @def.function
  (#eq? @_obj "exports"))

; `module.exports.foo = function () {}` / `= () => {}` -> Function `foo`
(assignment_expression
  left: (member_expression
    object: (member_expression
      object: (identifier) @_mod
      property: (property_identifier) @_exp)
    property: (property_identifier) @name)
  right: [(function_expression) (arrow_function)] @def.function
  (#eq? @_mod "module")
  (#eq? @_exp "exports"))

; `module.exports = { foo: function(){}, bar: () => {} }` -> Function per inline
; function-valued pair. Shorthand props (`{ a, b }`) that name top-level defs
; already resolve via the export map, so only inline functions need extracting.
(assignment_expression
  left: (member_expression
    object: (identifier) @_mod
    property: (property_identifier) @_exp)
  right: (object
    (pair
      key: (property_identifier) @name
      value: [(function_expression) (arrow_function)] @def.function))
  (#eq? @_mod "module")
  (#eq? @_exp "exports"))
