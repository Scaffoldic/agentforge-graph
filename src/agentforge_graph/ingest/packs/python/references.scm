; Python reference queries (feat-002).
; Calls only at v0.1: a plain call `f(...)` and an attribute call `recv.f(...)`.
; @call.callee is the called name; @call.recv is the receiver (BUG-006), so the
; resolver can bind `self.f()` to the enclosing class's method without guessing
; for other receivers. The extractor attributes the call to its enclosing
; definition and records it for pass-2 resolution.

(call
  function: (identifier) @call.callee) @call

(call
  function: (attribute
    object: (_) @call.recv
    attribute: (identifier) @call.callee)) @call
