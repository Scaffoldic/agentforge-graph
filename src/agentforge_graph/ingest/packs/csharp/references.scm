; C# reference queries (feat-002, pack-csharp).
; Plain call `F(...)` and member call `obj.F(...)`. Member calls are usually left
; unresolved (member access, ADR-0004).

(invocation_expression
  function: (identifier) @call.callee) @call

(invocation_expression
  function: (member_access_expression
    name: (identifier) @call.callee)) @call
