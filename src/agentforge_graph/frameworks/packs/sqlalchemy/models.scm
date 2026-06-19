; SQLAlchemy declarative models (feat-011). Capture every class; the pack then
; inspects each class body in code to decide whether it is a DataModel (has a
; ``__tablename__`` or ``Column(...)``/``mapped_column(...)`` fields). Body
; analysis is done in Python rather than the query so direct-child scoping
; (class-level fields only, never nested locals) stays precise.
(class_definition
  name: (identifier) @name) @model
