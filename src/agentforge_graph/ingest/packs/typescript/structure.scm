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

; --- imports ---
; `import { a, b } from "./mod"` -> module (relative path) + bound names
(import_statement
  (import_clause (named_imports (import_specifier name: (identifier) @import.name)))
  source: (string (string_fragment) @import.module)) @import
