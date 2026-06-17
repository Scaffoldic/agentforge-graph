; Rust reference queries (feat-002, pack-rust).
; Plain call `f(...)` and method call `x.f(...)`. @call.recv captures the
; receiver so `self.f()` binds to the enclosing impl's method (BUG-006); other
; receivers stay unresolved (member access, ADR-0004).

(call_expression
  function: (identifier) @call.callee) @call

(call_expression
  function: (field_expression
    value: (_) @call.recv
    field: (field_identifier) @call.callee)) @call
