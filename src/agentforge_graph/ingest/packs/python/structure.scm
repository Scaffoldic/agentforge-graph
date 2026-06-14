; Python structure queries (feat-002).
; Each definition pattern captures the definition node (@def.<kind>) and its
; identifier (@name) in one pattern, so the extractor pairs them via matches().
; Imports capture the module and (for `from` imports) the bound names.

; --- definitions ---
(class_definition
  name: (identifier) @name) @def.class

(function_definition
  name: (identifier) @name) @def.function

; --- imports ---
; `import a.b.c`  (optionally aliased) -> module only
(import_statement
  name: [(dotted_name) @import.module
         (aliased_import (dotted_name) @import.module)]) @import

; `from a.b import c, d`  -> module + one or more bound names
(import_from_statement
  module_name: (dotted_name) @import.module
  name: [(dotted_name) @import.name
         (aliased_import (dotted_name) @import.name)]) @import

; `from .mod import x` / `from . import x` (relative) -> the relative module
; text (leading dots + optional name, e.g. `.utils`, `..pkg.mod`, `.`) + names.
; resolve_import() resolves the dots against the importer's package (BUG-004).
(import_from_statement
  module_name: (relative_import) @import.module
  name: [(dotted_name) @import.name
         (aliased_import (dotted_name) @import.name)]) @import
