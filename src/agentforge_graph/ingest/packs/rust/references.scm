; Rust reference queries (feat-002, pack-rust).
; Plain call `f(...)` and method call `x.f(...)`. Method/path calls are usually
; left unresolved (member access, ADR-0004).

(call_expression
  function: (identifier) @call.callee) @call

(call_expression
  function: (field_expression
    field: (field_identifier) @call.callee)) @call
