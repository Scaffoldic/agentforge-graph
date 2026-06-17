; Ruby structure queries (feat-002, pack-ruby).
; Shares the capture vocabulary so edge kinds mean the same as other packs.

; --- definitions ---
; module + class are named containers -> Class; nested defs become methods.
(module
  name: (constant) @name) @def.class

(class
  name: (constant) @name) @def.class

; --- inheritance (INHERITS): `class B < A` ---
(class
  superclass: (superclass (constant) @base.name)) @base.def

; `def foo` -> Function (promoted to Method when nested in a class/module body).
(method
  name: (identifier) @name) @def.function

; `def self.foo` (class method) -> Method.
(singleton_method
  name: (identifier) @name) @def.method

; constant assignment (`PI = 3.14`) -> Variable. Only `constant` (Uppercase) lefts
; match, so local variables (lowercase identifiers) are not captured.
(assignment
  left: (constant) @name) @def.variable

; --- imports ---
; `require_relative "thor/command"` is always file-relative (bare or `./`),
; resolved in-repo via relative_bare. Plain `require "gem"` is load-path based
; (lib-root relative) and is left to a follow-up — capturing it here would
; mis-resolve against the importer's dir, so only require_relative is taken.
(call
  method: (identifier) @_req
  arguments: (argument_list (string (string_content) @import.module))
  (#eq? @_req "require_relative")) @import
