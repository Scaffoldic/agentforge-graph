; Go structure queries (feat-002, pack-go).
; Shares the capture vocabulary so edge kinds mean the same as other packs.
; A Go package is a *directory*: every `.go` file in a dir is one package, and
; same-package files reference each other with no import (handled in the resolver).

; --- definitions ---
(function_declaration
  name: (identifier) @name) @def.function

; methods are declared at package scope, attached to a receiver type. They're not
; AST-nested in the type, so they're file-owned here (receiver→method CONTAINS
; linkage is a follow-up); captured directly as Method.
(method_declaration
  name: (field_identifier) @name) @def.method

; `type T struct {…}` -> Class, `type T interface {…}` -> Interface.
(type_spec
  name: (type_identifier) @name
  (struct_type)) @def.class

(type_spec
  name: (type_identifier) @name
  (interface_type)) @def.interface

; defined types / aliases: `type Celsius float64`, `type ID = string`, `type
; Handler func(...)`. Listed underlying kinds exclude struct/interface so there's
; no double-match with the two patterns above.
(type_spec
  name: (type_identifier) @name
  [(type_identifier)
   (qualified_type)
   (pointer_type)
   (slice_type)
   (array_type)
   (map_type)
   (channel_type)
   (function_type)
   (generic_type)]) @def.type

(type_alias
  name: (type_identifier) @name) @def.type

; package-level const / var (anchored to source_file so locals don't inflate).
(source_file
  (const_declaration
    (const_spec name: (identifier) @name) @def.variable))
(source_file
  (var_declaration
    (var_spec name: (identifier) @name) @def.variable))

; --- imports ---
; `import "example.com/m/pkg"` (and grouped `import ( … )`) -> the path string.
; Go imports bind a *package*, not names; the resolver maps the path to a repo dir.
(import_spec
  (interpreted_string_literal
    (interpreted_string_literal_content) @import.module)) @import
