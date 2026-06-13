; JavaScript reference queries (feat-002, pack-js).
; Plain call `f(...)` and method/attribute call `x.f(...)`.

(call_expression
  function: (identifier) @call.callee) @call

(call_expression
  function: (member_expression
    property: (property_identifier) @call.callee)) @call
