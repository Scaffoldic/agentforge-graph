; ENH-020 C-full: JS/TS outbound HTTP calls.
; axios.get("…") / axios.post("…")
(call_expression
  function: (member_expression
    object: (identifier) @obj
    property: (property_identifier) @method)
  arguments: (arguments) @args) @call

; fetch("…") / axios("…")
(call_expression
  function: (identifier) @fn
  arguments: (arguments) @args) @call
