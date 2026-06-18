; C++ reference queries (feat-002, pack-cpp; Tier B — heuristic).
; Plain call `f(...)`; member/arrow calls (`this->f()`, `obj.f()`, `ptr->f()`)
; capture the receiver so `this->f()` binds to a method of the enclosing class;
; any other receiver is left unresolved (member access, ADR-0004). `ns::f()`
; qualified calls are not captured here.

(call_expression
  function: (identifier) @call.callee) @call

; `this->f()` / `obj.f()` / `ptr->f()` — the receiver is the field_expression's
; argument (`this` is a named node, captured by `(_)`).
(call_expression
  function: (field_expression
    argument: (_) @call.recv
    field: (field_identifier) @call.callee)) @call
