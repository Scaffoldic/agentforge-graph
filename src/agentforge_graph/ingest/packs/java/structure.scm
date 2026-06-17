; Java structure queries (feat-002, pack-java).
; Namespace/FQN import model (reuses the PHP mechanism, separator "."): a file
; declares a `package`; `import com.foo.Bar` resolves to the file declaring Bar.

; --- package (drives FQN import resolution) ---
(package_declaration
  (scoped_identifier) @namespace)

; --- definitions ---
(class_declaration
  name: (identifier) @name) @def.class

; --- inheritance (INHERITS): `class B extends A` (implemented interfaces are a
; separate relation, not captured here). ---
(class_declaration
  superclass: (superclass (type_identifier) @base.name)) @base.def

(interface_declaration
  name: (identifier) @name) @def.interface

; enum + record -> Class (named nominal types).
(enum_declaration
  name: (identifier) @name) @def.class

(record_declaration
  name: (identifier) @name) @def.class

; methods + constructors live in a class/interface body -> promoted to Method.
(method_declaration
  name: (identifier) @name) @def.function

(constructor_declaration
  name: (identifier) @name) @def.function

; --- imports ---
; `import com.foo.shapes.Shape;` -> the fully-qualified class name (FQN index).
(import_declaration
  (scoped_identifier) @import.module) @import
