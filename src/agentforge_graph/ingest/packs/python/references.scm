; Python reference queries (feat-002).
; Calls only at v0.1: a plain call `f(...)` and an attribute call `x.f(...)`.
; @call.callee is the called name; the extractor attributes the call to its
; enclosing definition and records it for pass-2 resolution.

(call
  function: (identifier) @call.callee) @call

(call
  function: (attribute
    attribute: (identifier) @call.callee)) @call
