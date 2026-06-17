; JavaScript reference queries (feat-002, pack-js).
; Plain call `f(...)` and method/attribute call `recv.f(...)`. @call.recv is the
; receiver (BUG-006), so `this.f()` binds to the enclosing class's method.

(call_expression
  function: (identifier) @call.callee) @call

(call_expression
  function: (member_expression
    object: (_) @call.recv
    property: (property_identifier) @call.callee)) @call
