; Rust structure queries (feat-002, pack-rust).
; Module path is derived from the file path (namespace_from_path), so a
; `use crate::a::b::Item` resolves to the file declaring Item. `mod` blocks are
; scopes, not def nodes (so items in them keep their correct kind).

; --- definitions ---
(struct_item
  name: (type_identifier) @name) @def.class

(enum_item
  name: (type_identifier) @name) @def.class

(union_item
  name: (type_identifier) @name) @def.class

; a trait is an interface (named method/contract container).
(trait_item
  name: (type_identifier) @name) @def.interface

; `impl Type { … }` / `impl Trait for Type { … }` -> attach methods to the Type
; (merges with the struct/enum node of the same name; methods nest -> Method).
(impl_item
  type: (type_identifier) @name) @def.class

; free functions; in an impl/trait body they promote to Method by nesting.
(function_item
  name: (identifier) @name) @def.function

; trait method signatures (`fn draw(&self);`).
(function_signature_item
  name: (identifier) @name) @def.function

(const_item
  name: (identifier) @name) @def.variable

(static_item
  name: (identifier) @name) @def.variable

(type_item
  name: (type_identifier) @name) @def.type

; --- imports ---
; `use crate::shapes::Shape;` -> path naming an item (FQN-style resolution).
; Grouped/glob uses (`use a::{B, C}`, `use a::*`) are a follow-up.
(use_declaration
  (scoped_identifier) @import.module) @import
