# ADR 0027: Extension-Owned Shopify Bulk Product Submission

## Status

Accepted for the user-authorized submission-only scope — 2026-09-15.

## Context

Supplier synchronization can introduce thousands of new products. Calling create_product once
per workflow item incurs repeated request and execution overhead. The user requested bulk
upload and clarified that the workflow should continue after acceptance, without waiting for
Shopify processing or checking status later.

## Decision

- The Shopify extension owns create_products_bulk: a typed array or optional JSONL artifact,
  complete input validation, staged upload and one fixed bulkOperationRunMutation.
- Existing create_product mapping and validation remain authoritative. Products are drafts;
  creating other variants or setting inventory remains separate existing behavior.
- The host external-effect identity is required before real I/O; test mode suppresses all I/O.
  Submission is one-shot. Unknown outcomes report timeout_unknown/nonretryable. Shopify's
  clientIdentifier is only a correlation hint, not provider-side deduplication.
- Submission success confirms acceptance only. The result includes the bulk operation ID and
  initial status, plus input count. Core gains no background orchestration responsibility.
- No status action, result download, webhook registration or notification is included. Automatic
  admin CSV-import emails must not be promised for API bulk mutation imports.
- The public SDK owns pinned HTTP and credential boundaries. Staged storage receives signed
  form fields without Admin API tokens. Caller-supplied upload URLs and mutations are forbidden.
- The outbound staged upload is registered under orchestrator retry ownership. The extension
  does not retry a submitted mutation; callers must reconcile ambiguous submissions first.

## Consequences

A workflow can continue quickly after dispatch, but cannot infer final per-row success from
its successful action result. A future completion notification requires separately scoped
webhook handling. Batches are bounded to 10000 rows and 100 MB, with JSONL artifacts preferred
for large input. No production throughput or automatic notification guarantee is introduced.
