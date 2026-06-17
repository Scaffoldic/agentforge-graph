; PHP structure queries (feat-002, pack-php).
; Namespace/FQN import model: a file declares one namespace; `use App\Foo\Bar`
; resolves to the file declaring class Bar in namespace App\Foo.

; --- namespace (drives FQN import resolution) ---
(namespace_definition
  name: (namespace_name) @namespace)

; --- definitions ---
(class_declaration
  name: (name) @name) @def.class

; --- inheritance (INHERITS): `class B extends A` (implemented interfaces are a
; separate relation, not captured here). ---
(class_declaration
  (base_clause (name) @base.name)) @base.def

(interface_declaration
  name: (name) @name) @def.interface

; a trait is a reusable unit of methods — model as Class (named method container).
(trait_declaration
  name: (name) @name) @def.class

; enum -> Class (a named nominal type; no dedicated Enum kind).
(enum_declaration
  name: (name) @name) @def.class

(function_definition
  name: (name) @name) @def.function

; methods live in a class/interface/trait body -> promoted to Method by nesting.
(method_declaration
  name: (name) @name) @def.function

; top-level + class constants -> Variable.
(const_element
  (name) @name) @def.variable

; --- imports ---
; `use App\Shapes\Shape;` -> the fully-qualified class name (resolved via FQN index).
(namespace_use_declaration
  (namespace_use_clause
    (qualified_name) @import.module)) @import
