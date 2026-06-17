; C++ reference queries (feat-002, pack-cpp; Tier B — heuristic).
; Plain call `f(...)`; member/qualified calls (`obj.f()`, `ns::f()`) are mostly
; left unresolved (member access, ADR-0004). Receiver capture for `this->f()` is
; deferred: the cpp pack does not yet model inline struct/class methods as
; symbols, so there is no method node to bind to (BUG-006 residual).

(call_expression
  function: (identifier) @call.callee) @call
