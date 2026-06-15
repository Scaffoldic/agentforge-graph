; JavaScript structure queries (feat-002, pack-js).
; Mirrors the TS pack; the only grammar delta is the class name node:
; JS `class_declaration` names are (identifier), not (type_identifier).
; Definitions may be wrapped in `export_statement`; queries match nested.

; --- definitions ---
(class_declaration
  name: (identifier) @name) @def.class

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
