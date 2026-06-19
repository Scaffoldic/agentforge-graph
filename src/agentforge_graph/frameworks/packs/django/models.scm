; Django models (feat-011). Capture every class; the pack inspects each class
; in code to decide whether it is a Django model — a base whose tail is `Model`
; (``class X(models.Model)``) or a ``models.*Field`` body assignment — so a
; plain class in a Django app never mints a false model. Body analysis is done
; in Python so direct-child scoping (class-level fields only) stays precise.
(class_definition
  name: (identifier) @name) @model
