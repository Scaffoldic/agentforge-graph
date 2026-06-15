; C++ reference queries (feat-002, pack-cpp; Tier B — heuristic).
; Plain call `f(...)`; member/qualified calls (`obj.f()`, `ns::f()`) are mostly
; left unresolved (member access, ADR-0004).

(call_expression
  function: (identifier) @call.callee) @call
