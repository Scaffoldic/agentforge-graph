; Go reference queries (feat-002, pack-go).
; Plain call `f(...)` and selector call `x.f(...)`. @call.recv is the operand, so
; a call on the method's receiver (`s.f()`) resolves to a method of the receiver's
; type (BUG-006); `pkg.Func` / other receivers stay unresolved (ADR-0004).

(call_expression
  function: (identifier) @call.callee) @call

(call_expression
  function: (selector_expression
    operand: (identifier) @call.recv
    field: (field_identifier) @call.callee)) @call
