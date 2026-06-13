---
title: Payment idempotency keys are client-side
status: accepted
date: 2025-11-03
---

# ADR-0012: Payment idempotency keys

Supersedes ADR-0007.

## Context

Retries were creating duplicate charges.

## Decision

`src/app/payments.py` must generate idempotency keys client-side. The
`PaymentService` class enforces this for every `charge`.

## Consequences

Clients must send a key header.
