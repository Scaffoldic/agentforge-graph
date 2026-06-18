; Python structure queries (feat-002).
; Each definition pattern captures the definition node (@def.<kind>) and its
; identifier (@name) in one pattern, so the extractor pairs them via matches().
; Imports capture the module and (for `from` imports) the bound names.

; --- definitions ---
(class_definition
  name: (identifier) @name) @def.class

(function_definition
  name: (identifier) @name) @def.function

; --- inheritance (INHERITS) ---
; a base class named by a bare identifier: `class B(A)` -> base `A`.
(class_definition
  superclasses: (argument_list (identifier) @base.name)) @base.def

; a qualified base `class B(mod.Base)` -> base `mod.Base`; the resolver splits the
; receiver and binds it via the importing module alias (`import mod`).
(class_definition
  superclasses: (argument_list (attribute) @base.name)) @base.def

; --- imports ---
; `import a.b.c` -> module only (the receiver in code is the dotted path itself).
(import_statement
  name: (dotted_name) @import.module) @import

; `import a.b.c as x` -> module + the alias `x` as the local binding name, so a
; whole-module import bound to a short alias (`import numpy as np`) makes `np.f()`
; / `extends np.Base` resolve to module `a.b.c`'s exports (BUG-006).
(import_statement
  name: (aliased_import
    (dotted_name) @import.module
    alias: (identifier) @import.default)) @import

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
