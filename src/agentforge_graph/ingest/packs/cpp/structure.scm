; C++ structure queries (feat-002, pack-cpp; Tier B — structure + heuristic refs).
; Namespaces are scopes, not captured as defs (so free functions inside them stay
; Function, not Method). Header/impl split: methods are declared in the class body
; and may be defined out-of-line as `Type::method`.

; --- definitions ---
(class_specifier
  name: (type_identifier) @name) @def.class

(struct_specifier
  name: (type_identifier) @name) @def.class

(enum_specifier
  name: (type_identifier) @name) @def.class

; free function definition: `double compute(double x) { … }`
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @name)) @def.function

; out-of-line method definition: `double Circle::area() const { … }`
(function_definition
  declarator: (function_declarator
    declarator: (qualified_identifier
      name: (identifier) @name))) @def.function

; in-class method declaration: `double area() const;`
(field_declaration
  declarator: (function_declarator
    declarator: (field_identifier) @name)) @def.function

; constructor/destructor declaration: `Circle(double r);`
(declaration
  declarator: (function_declarator
    declarator: (identifier) @name)) @def.function

; --- imports ---
; `#include "geo/shape.h"` (quoted -> in-repo, relative). `<system>` is skipped.
(preproc_include
  (string_literal (string_content) @import.module)) @import
