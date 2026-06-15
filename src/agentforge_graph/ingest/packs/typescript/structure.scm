; TypeScript structure queries (feat-002, pack-ts).
; Mirrors the Python pack's capture vocabulary so edge kinds mean the same.
; Definitions may be wrapped in `export_statement`; queries match nested.

; --- definitions ---
(class_declaration
  name: (type_identifier) @name) @def.class

; `abstract class Foo {}` is a distinct node from class_declaration; capture it
; as the same Class kind so abstract base classes + their methods are extracted
; (BUG-005). JS has no `abstract`, so this is TS-only.
(abstract_class_declaration
  name: (type_identifier) @name) @def.class

(function_declaration
  name: (identifier) @name) @def.function

; methods live in a class_body -> promoted to METHOD by the extractor
(method_definition
  name: (property_identifier) @name) @def.function

; --- TS type surface (ENH-008) ---
; `interface Foo {}` -> Interface (the dominant way TS describes contracts).
(interface_declaration
  name: (type_identifier) @name) @def.interface

; `enum E {}` and `const enum E {}` -> Class (no dedicated Enum kind; a named
; nominal type with members). Both parse as enum_declaration with an identifier.
(enum_declaration
  name: (identifier) @name) @def.enum

; `type ID = ...` -> TypeAlias.
(type_alias_declaration
  name: (type_identifier) @name) @def.type

; --- value bindings (ENH-008, shared with JS) ---
; `const f = (…) => …` / `const f = function () {}` -> Function (named from the
; binding). Captured at any depth — these are genuine functions.
(lexical_declaration
  (variable_declarator
    name: (identifier) @name
    value: [(arrow_function) (function_expression)])) @def.function

; module-level const data tables / const-object enums -> Variable. Scoped to the
; top level (program / export) so locals inside function bodies don't inflate the
; graph. Only object/array initializers — NOT call results: `const x =
; require(...)` is an import binding (BUG-006), and call-bound public constants
; (e.g. zod's `ZodIssueCode = arrayToEnum([...])`) stay findable via their
; companion `type X = ...` alias, captured above as a TypeAlias.
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

; --- imports ---
; `import { a, b } from "./mod"` -> module (relative path) + bound names
(import_statement
  (import_clause (named_imports (import_specifier name: (identifier) @import.name)))
  source: (string (string_fragment) @import.module)) @import
