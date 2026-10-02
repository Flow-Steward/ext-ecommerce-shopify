# Shopify

A closed subset of the Shopify Admin GraphQL API `2026-07` for inventory, catalog and order
automation, typed and scoped to project-owned Shopify stores.

The surface is deliberately narrow, and narrow in a specific way: it reads what a store stocks,
sells and has been ordered, and it makes a small set of bounded changes to stock, catalog records
and fulfillments. It is not a general Shopify client. Nothing here deletes, archives, cancels,
refunds or publishes; nothing touches customers, discounts, collections or content; nothing
notifies a customer; and there is no webhook, no REST Admin API, bulk creation of draft products,
and no way to run GraphQL of your own. Authorization is OAuth, and it is the only OAuth here: the
extension holds no other credential and performs no other flow.

## What it can do

A closed surface over Shopify Admin GraphQL `2026-07`: inventory, catalog and orders.
**Thirty-three operations, thirty-two of which contact Shopify, twelve of which change anything.**

| Operation | Kind | Contacts Shopify | In workflows |
|---|---|---:|---:|
| `validate_connection_settings` | source | No | No |
| `test_connection` | source | Yes | Yes |
| `get_shop` | source | Yes | Yes |
| `list_locations` | source | Yes | Yes |
| `list_inventory_items` | source | Yes | Yes |
| `get_inventory_item` | source | Yes | Yes |
| `get_inventory_levels_batch` | source | Yes | Yes |
| `set_inventory_quantities` | action | Yes | Yes |
| `list_products` | source | Yes | Yes |
| `export_products` | source | Yes | Yes |
| `get_product` | source | Yes | Yes |
| `list_product_variants` | source | Yes | Yes |
| `get_product_variant` | source | Yes | Yes |
| `list_catalog_metafields` | source | Yes | Yes |
| `list_product_media` | source | Yes | Yes |
| `create_product` | action | Yes | Yes |
| `create_products_bulk` | action | Yes | Yes |
| `update_product` | action | Yes | Yes |
| `create_product_variants_batch` | action | Yes | Yes |
| `update_product_variants_batch` | action | Yes | Yes |
| `set_catalog_metafields` | action | Yes | Yes |
| `update_product_media_alt` | action | Yes | Yes |
| `list_orders` | source | Yes | Yes |
| `get_order` | source | Yes | Yes |
| `list_order_line_items` | source | Yes | Yes |
| `list_order_metafields` | source | Yes | Yes |
| `list_order_fulfillment_orders` | source | Yes | Yes |
| `get_fulfillment_order` | source | Yes | Yes |
| `list_order_fulfillments` | source | Yes | Yes |
| `update_order_metadata` | action | Yes | Yes |
| `set_order_metafields` | action | Yes | Yes |
| `create_fulfillment` | action | Yes | Yes |
| `update_fulfillment_tracking` | action | Yes | Yes |

There is nothing else. No product or order deletion, no archive, unpublish, cancel, close,
reopen, refund, return, order edit or mark-paid. No collections, publications, discounts,
customers or draft orders. No generic file upload, replacement or deletion — the single Files
API exception is changing one media item's alt text. No customer notification of any kind: both
fulfillment mutations hard-code `notifyCustomer: false`, and no operation sends an invoice.

## Optional product export details

`export_products` retains its optional Shopify `filter` and reads all matching product pages
into one JSONL artifact. `first` controls the base product page size, not the total export size.
Three optional booleans default to `false`:

| Parameter | Fields added to each exported product |
|---|---|
| `include_images` | `images`: media ID, `url`, `alt`; `image_count` |
| `include_variants` | `variants`: ID, title, SKU, decimal-string price/compare-at price and selected options |
| `include_inventory` | Automatically includes variants; adds each variant's `inventory_item` with ID, tracking flag and `levels` containing location ID/name and a quantities map |

Inventory quantities include available, on_hand, committed, incoming, reserved, damaged,
safety_stock and quality_control. Location quantities are not interchangeable with a store-wide
available total. Untracked items retain `tracked: false`; missing levels do not imply zero stock.
Inventory details require `read_inventory` or `write_inventory`, plus `read_locations` for names.
The standard connection already requests inventory and location scopes.

Unrequested fields are absent: omitted `image_count` means images were not requested, whereas
`image_count: 0` means no image media were returned. Pending/failed image media still count and
may have a null URL. URLs are exported; image binaries are not downloaded.

Example action input for a supplier image audit:

```json
{"connection_ref": "your-connection", "filter": "vendor:Acme", "include_images": true}
```

For empty descriptions, use the existing `description_html` field with `text.html_to_text`
and a Tabular Feed empty/length filter. To audit missing images, filter `image_count` equal to 0.

Related records are read in bounded batches, and every nested cursor is followed, including
products with more than 250 variants/images and items stocked at multiple locations. This adds
requests and export time. Only the current base product page and its details are assembled in
memory; unusually large per-product data still increases memory use. Export reads retry
throttling up to five times with bounded delays (1, 2, 4, 8, 16 seconds, extended by Retry-After
up to 30 seconds). Persistent throttling, denied scopes or incomplete responses fail the export;
no successful partial artifact is returned. Reads are not a transactional snapshot if catalog
content changes during export. This remains cursor-based export, not Shopify Bulk Operations.

## Images on new products

Both `create_product` and each row of `create_products_bulk` accept optional `images`:

```json
{"title":"Boots","handle":"supplier-a-boots","images":[{"url":"https://supplier.example/boots.jpg","alt":"Winter boots"}]}
```

Supply up to 250 publicly accessible HTTPS image URLs per product; `alt` is optional.
Shopify downloads and hosts the images. URLs must remain accessible during asynchronous
processing. Local files, binary uploads, image replacement and resizing are not provided here.
The input URL is limited to 2048 characters and alt text to 512 characters.
Omitting `images` or supplying an empty array creates a product without images.

Product creation success and bulk completion do not guarantee that every image is ready.
Use `list_product_media` and its status field to check `READY` or `FAILED` after processing.
A 2048×2048 source stays a supplier/content preparation requirement; this action does not
crop, pad or upscale it. See [Shopify CreateMediaInput](https://shopify.dev/docs/api/admin-graphql/2026-07/input-objects/CreateMediaInput).

## Bulk creation of new products

`create_products_bulk` submits a batch for asynchronous Shopify processing. Supply exactly one:

- `products`: 1–10000 objects with the same fields as `create_product`, without `connection_ref` per row.
- `artifact_handle`: a UTF-8 JSONL artifact, one such object per line, up to 10000 rows and 100 MB.

Every row requires `title` and `handle`. All rows are validated before contacting Shopify;
duplicate handles within the batch are refused. Products are drafts with only the initial
variant, matching `create_product`. Use the existing variant and inventory actions afterwards.

Example:

```json
{"connection_ref":"your-connection","products":[{"title":"Boots","handle":"supplier-a-boots","vendor":"Acme"}]}
```

The action uploads a Shopify JSONL variables file and returns `bulk_operation.id`, the initial
status, `client_identifier`, and `item_count`. External-effect success means Shopify accepted
the submission; it does not mean every product was created. No waiting loop is performed.

The workflow continues after Shopify accepts the submission. This action does not poll, download
results, or arrange notifications. A successful submission does not guarantee every row succeeds.
Save the returned bulk operation ID and original input for later reconciliation if needed.

Shopify documents automatic email for CSV imports through its admin, not for this API path.
Completion notifications require a separate `bulk_operations/finish` webhook integration;
none is configured here. Do not label submission success as "all products imported".

A host external-effect ID is required for real submissions; rehearsal suppresses all writes and
file reads. `clientIdentifier` is a correlation hint, not a Shopify deduplication guarantee.
It is returned on submission only; Shopify does not expose it on status reads. A timeout after
submission is an unknown outcome and is never automatically resubmitted. Reconcile in Shopify
before any manual retry. Retrying with a new workflow effect ID can create another batch.

Staged transfers use Shopify-issued HTTPS Google Storage URLs through the public pinned HTTP SDK;
Admin API tokens are never sent to storage. This does not add a generic upload or GraphQL action.
Processing time and concurrent bulk limits are
controlled by Shopify; this integration does not promise a fixed creation rate.

References: [Shopify bulk imports](https://shopify.dev/docs/api/usage/bulk-operations/imports).

## Connection

One connection type, `shopify_admin`, authorized through the OAuth authorization code grant. There
is no Admin API access token to create, paste, or store.

**The Shopify app is yours.** A project-scoped OAuth configuration holds the app's `client_id` and
its encrypted `client_secret`. The extension declares everything Shopify-specific about the flow —
the `.myshopify.com` suffix and the shape of a store label, the fixed `/admin/oauth/authorize` and
`/admin/oauth/access_token` paths, the comma-separated scopes, the absence of PKCE, the omitted
`token_type`, and how the callback signature is computed. None of it lives in core.

**Adding a connection asks for the store and nothing else.** The value is normalized to
`store-name.myshopify.com` and used to build that store's own authorization URL. What is stored is
not what was typed: after the callback's HMAC-SHA256 signature is verified against the client
secret, the store name inside Shopify's answer becomes `connection_config.oauth.subject`, and every
later request — including refresh — is built from that. The runtime reads only
`secrets.access_token`.

**Access expires and rotates.** The grant is requested with `expiring=1`, so Shopify returns an
access token, a refresh token, and both lifetimes; the platform refreshes ahead of expiry under the
existing per-connection lock and reads the durations from Shopify rather than assuming them.

**One connection per store per app.** Shopify keeps a single token per app and store, so a second
authorization would retire the first one's token. A duplicate is refused before the code is
exchanged. Separate OAuth configurations may hold the same store, because they can be separate
Shopify apps.

The eight scopes below cover all 33 operations. Shopify grants each write scope its matching read
permission, but the fields selected by `list_locations` require the distinct `read_locations`
scope in addition to the inventory scope:

```
write_inventory  read_locations  write_products  write_files  write_orders
write_assigned_fulfillment_orders  write_merchant_managed_fulfillment_orders
write_third_party_fulfillment_orders
```

The full eight-scope set is required, not a menu. Shopify presents a required set to the merchant
whole, so it is accepted or declined rather than trimmed: a grant that comes back short means the
app version asked for less, not that anyone picked and chose, and it creates no connection.
`test_connection` returns `capabilities` as a readable list of eligible operation IDs and keeps the
full per-operation diagnostics in `capability_scope_matrix`, keyed by operation ID. That matrix is
how an older stale grant is identified; the fix is on the app side — correct the scopes, release a
version, authorize the store again.

A project may hold several independent Shopify connections. Every operation names the connection it
runs against; the host hydrates that connection for one invocation and nothing survives it.

## Design rules this bundle holds itself to

**The registry is closed.** `runtime/catalog.py` declares thirty-three rows. An operation id that is not a
key in `dispatcher.OPERATION_REGISTRY` is refused before the connection is hydrated and before any
transport object exists. `contracts/operation_manifest.yaml`, `contracts/step_ui_manifest.yaml`,
`ui/actions/actions.yaml`, `contracts/artifact_policies.yaml` and the `external_effects` rows in
`extension.yaml` are generated from that registry and held in exact parity by the tests.

**There are thirty-two public-operation GraphQL documents.** They are written out in
`runtime/documents.py`. Nothing is interpolated into them; every caller value travels as a GraphQL
variable, including the SKU search string, which is built inside the extension.

**The endpoint has one source.** It is always
`https://{verified_shop_domain}/admin/api/2026-07/graphql.json`, derived from the OAuth subject
Shopify confirmed in the signed callback and the pinned API version. A workflow cannot supply a URL,
cannot name the store, and the transport refuses to send anywhere else.

**The manifest is executed, not restated.** `runtime/schema.py` runs each operation's published
input schema as written, so a nested `required` list is enforced rather than decorative:
`quantities: [{}]` fails locally, with the same rule the manifest publishes. Only the keyword subset
the Flow Steward host itself executes is supported, so an operation cannot declare a rule the
platform would silently ignore.

**Inputs must describe a usable change.** Metafield namespaces must contain 3–255 characters
and keys 2–64; the explicit compare digest remains required. Fulfillment tracking URLs require
an equally sized numbers array, matched by position; company-only or numbers-only tracking is
still supported. An empty `inventory_item` object alone is not a variant update, while
`tracked: false`, zero cost, and a separate price change remain valid. These checks refuse
invalid input before any outbound request.

**The token is never observable.** It is a private field on a frozen dataclass with `__repr__` and
`__str__` overridden, is used only to build the `X-Shopify-Access-Token` header, and appears in no
result, log line, exception or connection-test diagnostic.

**Nothing survives an invocation.** No module-level session, client, cached connection or "active
store". Everything lives in the call frame.

**Nothing else opens a connection.** The bundle contains no `urlopen`, no `requests`, no `httpx`,
no `ShopifyAPI` and no `shopifyapp`. `urllib.request.Request` is imported only as a value object
describing a request; `open_pinned_url` is what sends it. `tests/test_security_boundaries.py`
walks every module's AST and fails if any of those names reappears.

**Uncertainty is reported as uncertainty.** A timeout or disconnect after the mutation has been sent
returns `timeout_unknown` with `definitely_no_external_effect: false`. It is never reported as
success and it is never retried.

## Operation notes

`create_product` returns both the draft `product` and `product_variants`, an array containing its
one initial variant. The array uses the same result field and variant shape as the variant batch
operations, including the variant id and `inventory_item.id`, so a workflow can map it to
`update_product_variants_batch` and the inventory item to `set_inventory_quantities` without a
store-wide lookup. When options are supplied, Shopify builds this initial variant from the first
value of each option; the remaining combinations are still created explicitly with the variant
batch operation.

`list_locations` and `list_inventory_items` return one page and the cursor for the next one. They do
not auto-paginate: pass `page_info.end_cursor` back as `after`.

`get_inventory_levels_batch` preserves the order of `inventory_item_ids` and answers for every id it
was given. An id Shopify cannot resolve comes back with `found: false`; an item that is simply not
stocked at that location comes back with `level: null`. Neither is an operation failure — losing a
batch of 250 because one id was retired would be the worse outcome.

`set_inventory_quantities` writes absolute `available` quantities with `reason: correction` and a
`referenceDocumentUri` of `gid://flow-steward/ExternalEffect/{external_effect_id}`. The same
external effect id is sent as Shopify's `@idempotent` key. `change_from_quantity` is required on
every entry and may be an explicit `null`; that is how a caller opts out of the compare-and-swap
check, and requiring the key means nobody opts out by forgetting it. `compareQuantity` and
`ignoreCompareQuantity` were removed by Shopify's compare-and-swap redesign and appear nowhere in
this bundle.

When every requested quantity equals its non-null `change_from_quantity`, Shopify may confirm the
no-op with no user errors and no adjustment group. The operation reports that CAS-proven unchanged
batch as succeeded with `inventory_adjustment_group: null`. A missing group remains
`timeout_unknown` whenever any entry expected a change or opted out of compare-and-swap.

Setting a quantity to `0` is an intentional business effect. Nothing is deleted, but the item stops
being purchasable at that location.

## Shopify AI Toolkit validation evidence

Every final GraphQL document was validated against Admin API `2026-07` with the Shopify AI Toolkit
before it was committed, with `OPT_OUT_INSTRUMENTATION=true` set. The toolkit is development
tooling: nothing it produces is part of this bundle, no Shopify app was scaffolded, no
`shopify.app.toml` or `shopify.extension.toml` was created, no store-management execution was used,
and no toolkit, plugin, MCP or Node.js dependency is committed anywhere in this repository.

```
scripts/validate.mjs --version 2026-07 --artifact-id <document id> --revision <n> --code '<document>'
```

| Document | Artifact id | Revision | API version | Result |
|---|---|---:|---|---|
| `test_connection` | `fs-shopify-01_test_connection` | 1 | `2026-07` | ✅ VALID |
| `get_shop` | `fs-shopify-02_get_shop` | 1 | `2026-07` | ✅ VALID |
| `list_locations` | `fs-shopify-03_list_locations` | 1 | `2026-07` | ✅ VALID |
| `list_inventory_items` | `fs-shopify-04_list_inventory_items` | 1 | `2026-07` | ✅ VALID |
| `get_inventory_item` | `fs-shopify-05_get_inventory_item` | 1 | `2026-07` | ✅ VALID |
| `get_inventory_levels_batch` | `fs-shopify-06-levels-batch` | 2 | `2026-07` | ✅ VALID |
| `set_inventory_quantities` | `fs-shopify-07_set_inventory_quantities` | 1 | `2026-07` | ✅ VALID |
| `list_products` | `fs-shopify-list_products` | 2 | `2026-07` | ✅ VALID |
| `export_products` | `fs-shopify-export-products-20260912` | 1 | `2026-07` | ✅ VALID |
| `create_products_bulk` | `fs-bulk-products-submit-20260915` | 2 | `2026-07` | ✅ VALID |
| `get_product` | `fs-shopify-get_product` | 1 | `2026-07` | ✅ VALID |
| `list_product_variants` | `fs-shopify-list_product_variants` | 1 | `2026-07` | ✅ VALID |
| `get_product_variant` | `fs-shopify-get_product_variant` | 1 | `2026-07` | ✅ VALID |
| `list_catalog_metafields` | `fs-shopify-list_catalog_metafields` | 1 | `2026-07` | ✅ VALID |
| `list_product_media` | `fs-shopify-list_product_media` | 1 | `2026-07` | ✅ VALID |
| `create_product` | `fs-shopify-create_product` | 2 | `2026-07` | ✅ VALID |
| `update_product` | `fs-shopify-update_product` | 1 | `2026-07` | ✅ VALID |
| `create_product_variants_batch` | `fs-shopify-create_product_variants_batch` | 1 | `2026-07` | ✅ VALID |
| `update_product_variants_batch` | `fs-shopify-update_product_variants_batch` | 1 | `2026-07` | ✅ VALID |
| `set_catalog_metafields` | `fs-shopify-set_catalog_metafields` | 2 | `2026-07` | ✅ VALID |
| `update_product_media_alt` | `fs-shopify-update_product_media_alt` | 1 | `2026-07` | ✅ VALID |
| `list_orders` | `fs-shopify-list_orders` | 1 | `2026-07` | ✅ VALID |
| `get_order` | `fs-shopify-get_order` | 1 | `2026-07` | ✅ VALID |
| `list_order_line_items` | `fs-shopify-list_order_line_items` | 1 | `2026-07` | ✅ VALID |
| `list_order_metafields` | `fs-shopify-list_order_metafields` | 1 | `2026-07` | ✅ VALID |
| `list_order_fulfillment_orders` | `fs-shopify-list_order_fulfillment_orders` | 1 | `2026-07` | ✅ VALID |
| `get_fulfillment_order` | `fs-shopify-get_fulfillment_order` | 1 | `2026-07` | ✅ VALID |
| `list_order_fulfillments` | `fs-shopify-list_order_fulfillments` | 1 | `2026-07` | ✅ VALID |
| `update_order_metadata` | `fs-shopify-update_order_metadata` | 1 | `2026-07` | ✅ VALID |
| `set_order_metafields` | `fs-shopify-set_order_metafields` | 2 | `2026-07` | ✅ VALID |
| `create_fulfillment` | `fs-shopify-create_fulfillment` | 1 | `2026-07` | ✅ VALID |
| `update_fulfillment_tracking` | `fs-shopify-update_fulfillment_tracking` | 1 | `2026-07` | ✅ VALID |

The bulk submission document passed validation at revision 2 after removing an unsupported response field. Internal staging (`fs-bulk-products-stage-20260915`, revision 1) and per-row creation (`fs-bulk-products-row-20260915`, revision 2) also passed Shopify schema validation. The internal per-row mutation is fixed and cannot be supplied by callers. Live bulk import and webhook evidence is recorded in `logs/quality/shopify-bulk-live-20260915.md`.

The 31 existing documents retain their prior validation evidence; four carry revision 2 because
the document itself was later improved, not because a validation failed:

- `get_inventory_levels_batch` gained `includeInactive`, which had been applied only to the
  response and so could never surface an inactive level.
- `list_products` gained the fixed ID sort and optional product filter used by both one-page reads
  and complete streaming exports.
- `set_catalog_metafields` and `set_order_metafields` gained their owner ids, without which a
  confirmed metafield could not be correlated back to the entry that requested it.

Each operation publishes exactly one `required_oauth_scopes` all-of list. The connection requests
the union of those lists and rejects an incomplete OAuth callback. `test_connection` compares an
existing grant with the same operation lists, returns eligible IDs in `capabilities`, and publishes
the complete keyed `capability_scope_matrix` so an older stale authorization can be diagnosed and
reauthorized; it does not define a second scope policy.

Toolkit validation is a schema check, not a substitute for the repository tests. Both are required.

## Layout

```
extension.yaml                  manifest v2: identity, effects, contract refs, entrypoint
main.py                         subprocess entrypoint: bounded stdin, sanitized bounded output
dispatcher.py                   the closed registry, checked before anything else happens
health.py                       health command
contracts/                      connection types, operation manifest, step UI, artifact policies
runtime/catalog.py              the 31 declared operations, with their own schemas
runtime/documents.py            the 30 GraphQL documents, and nothing else
runtime/schema.py               executes the published input schema
runtime/validation.py           id typing, duplicate-pair refusal, defaults, runtime context
runtime/connection.py           domain normalization, secret handling, endpoint derivation
runtime/transport.py            one POST to one URL, over the public SDK
runtime/operations.py           one handler per operation, and the result shapes
runtime/errors.py               the stable error vocabulary and the Shopify mappings
tests/reference/                offline generators for the contracts and the generated pages
ui/                             connection form, setup guide, inventory reference, changelog
```

## Tests

Every test runs offline against mocked Shopify responses. No production credential and no live store
is needed, and none is referenced.

```bash
python -m pytest extensions/flowsteward_shopify/tests -x -v
```

Regenerate the contracts and the generated pages after changing the registry:

```bash
python tests/reference/refresh_contracts.py
```

Image creation documents passed official Shopify validation: `fs-product-images-create-20260915` and `fs-product-images-bulk-row-20260915`, revision 1.
