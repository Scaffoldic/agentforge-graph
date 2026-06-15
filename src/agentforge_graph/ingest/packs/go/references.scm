; Go reference queries (feat-002, pack-go).
; Plain call `f(...)` and selector call `x.f(...)` (method or `pkg.Func` — the
; latter is package-qualified and usually stays unresolved, ADR-0004).

(call_expression
  function: (identifier) @call.callee) @call

(call_expression
  function: (selector_expression
    field: (field_identifier) @call.callee)) @call
