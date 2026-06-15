; C# structure queries (feat-002, pack-csharp).
; Namespace-prefix import model: `using App.Geo` names a *namespace* (not a class),
; so it resolves to every in-repo file declaring that namespace.

; --- namespace (block or file-scoped) ---
(namespace_declaration
  name: (_) @namespace)
(file_scoped_namespace_declaration
  name: (_) @namespace)

; --- definitions ---
(class_declaration
  name: (identifier) @name) @def.class

(interface_declaration
  name: (identifier) @name) @def.interface

; struct + enum + record -> Class (named nominal types).
(struct_declaration
  name: (identifier) @name) @def.class

(enum_declaration
  name: (identifier) @name) @def.class

(record_declaration
  name: (identifier) @name) @def.class

; methods + constructors live in a type body -> promoted to Method.
(method_declaration
  name: (identifier) @name) @def.function

(constructor_declaration
  name: (identifier) @name) @def.function

; --- imports ---
; `using System;` / `using App.Shapes;` -> a namespace (resolved to its files).
(using_directive
  [(identifier) (qualified_name)] @import.module) @import
