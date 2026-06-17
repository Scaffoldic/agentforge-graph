; C# reference queries (feat-002, pack-csharp).
; Plain call `F(...)` and member call `obj.F(...)`. @call.recv captures the
; receiver so `this.F()` binds to the enclosing class's method (BUG-006); other
; receivers stay unresolved (member access, ADR-0004).

(invocation_expression
  function: (identifier) @call.callee) @call

(invocation_expression
  function: (member_access_expression
    expression: _ @call.recv
    name: (identifier) @call.callee)) @call
