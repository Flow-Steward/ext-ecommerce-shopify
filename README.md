# Shopify

Shopify Admin GraphQL API `2026-07` for inventory, catalog and order automation, typed and
scoped to project-owned Shopify stores.

The surface is a fixed set of operations, and each one covers its Shopify endpoint completely:
every input field Shopify's mutation accepts, every filter and sort its list offers, and every
scalar and money field of the record it returns. What is deliberately not reachable is listed
with its reason on the **Shopify API coverage** page (`ui/pages/api-coverage.yaml`), and the
tests compare every operation with Shopify's official schema field by field. It is not a general
Shopify client: nothing here deletes, cancels or refunds, there is no webhook, no REST Admin API
and no way to run GraphQL of your own. Authorization is OAuth, and it is the only OAuth here: the
extension holds no other credential and performs no other flow.

## What it can do

A fixed surface over Shopify Admin GraphQL `2026-07`: inventory, catalog and orders.
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
| `update_product_media` | action | Yes | Yes |
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

There is nothing else. No product or order deletion, cancel, close, reopen, refund, return, order
edit or mark-paid. No collection, publication, discount, customer or draft-order management. A
product becomes sellable only when a step sets `status: ACTIVE`, and a customer is emailed only
when a fulfillment step sets `notify_customer: true`; both default to the cautious choice.

## Coverage of the official API

`tests/test_admin_api_coverage.py` compares every operation with a slice of Shopify's public
Admin GraphQL `2026-07` schema — the same schema file the Shopify AI Toolkit validator and Dev MCP
use — kept in `tests/reference/admin_schema_2026_07.json`. It fails when:

- a document selects a field that does not exist or is deprecated;
- a list argument Shopify offers is neither used nor excluded with a reason;
- a record lacks a scalar or money field of its Shopify type that is not excluded with a reason;
- a document's selection and its record table disagree;
- a field of a mutation's input object cannot be reached from the operation's input — proved by
  running each operation and reading the variables it actually sends;
- a document could exceed Shopify's 1000-point single-query cost limit at its maximum page size.

The exclusions live in `runtime/coverage.py` and are rendered for users on the
**Shopify API coverage** page. In short: ids a record being created cannot have yet; the
`identifier` that would turn product creation into an upsert; Shopify's `last`/`before`
backward paging; customer emails, phones and IP addresses on order reads, which are protected
customer data; the store owner's personal email and name.

## Optional product export details

`export_products` reads all matching product pages into one JSONL artifact. Besides Shopify's
`filter`, `sort_key`, `reverse` and `saved_search_id`, three optional booleans default to `false`:

| Parameter | Fields added to each exported product |
|---|---|
| `include_images` | `images`: media id, `url`, `alt`, `width`, `height`, processing `status`; `image_count` |
| `include_variants` | `variants`: the full variant record, as `get_product_variant` returns it |
| `include_inventory` | Automatically includes variants; adds `levels` to each variant's `inventory_item`, with location id/name and a quantities map |

Inventory quantities include available, on_hand, committed, incoming, reserved, damaged,
safety_stock and quality_control. Location quantities are not interchangeable with a store-wide
available total. Untracked items retain `tracked: false`; missing levels do not imply zero stock.
Inventory details require `read_inventory` or `write_inventory`, plus `read_locations` for names.
The standard connection already requests inventory and location scopes.

Unrequested fields are absent: omitted `image_count` means images were not requested, whereas
`image_count: 0` means no image media were returned. Pending/failed image media still count and
may have a null URL and size. URLs are exported; image binaries are not downloaded.

### Products that need attention

`quality_filter` exports only the products with catalog gaps, each with a `quality_issues` list.
Shopify's product search cannot filter on these, so the whole matching catalog is read and
checked; `scanned_count` reports how many products were read, `item_count` how many matched.

| Check | Issue code |
|---|---|
| `missing_images: true` | `missing_images` |
| `min_image_width` / `min_image_height`, or `below_recommended_image_size: true` (2048 × 2048) | `image_too_small` |
| `missing_image_alt_text: true` | `image_missing_alt_text` |
| `missing_description: true` | `missing_description` |
| `min_description_length` (plain-text characters, tags not counted) | `description_too_short` |
| `missing_fields`: `vendor`, `product_type`, `category`, `tags`, `seo_title`, `seo_description`, and on any variant `sku`, `barcode`, `weight`, `price` | `missing_<field>` |

`match: "any"` (default) exports a product with at least one checked problem; `match: "all"`
only products with every checked problem. Images and variants are read automatically when a
check needs them.

```json
{"connection_ref": "your-connection", "filter": "status:active",
 "quality_filter": {"below_recommended_image_size": true, "missing_fields": ["sku", "barcode"]}}
```

Related records are read in bounded batches, and every nested cursor is followed, including
products with more than 250 variants/images and items stocked at multiple locations. This adds
requests and export time. Only the current base product page and its details are assembled in
memory; unusually large per-product data still increases memory use. Export reads retry
throttling up to five times with bounded delays (1, 2, 4, 8, 16 seconds, extended by Retry-After
up to 30 seconds). Persistent throttling, denied scopes or incomplete responses fail the export;
no successful partial artifact is returned. Reads are not a transactional snapshot if catalog
content changes during export. This remains cursor-based export, not Shopify Bulk Operations.

## Creating a product with its variants and images

`create_product` creates the product and every variant in one atomic Shopify call
(`productSet`): SKU, price, barcode, weight and starting stock go in with it, so no follow-up
variant or stock step is needed.

```json
{"title": "Boots", "handle": "supplier-a-boots", "status": "DRAFT",
 "variants": [{"sku": "BOOT-42", "price": "49.90", "barcode": "4006381333931",
   "inventory_item": {"tracked": true, "measurement": {"weight": {"value": 1.2, "unit": "KILOGRAMS"}}},
   "inventory_quantities": [{"location_id": "gid://shopify/Location/1", "name": "available", "quantity": 5}]}],
 "media": [{"source_url": "https://supplier.example/boots.jpg", "alt": "Winter boots"}],
 "image_files": [{"artifact_handle": "artifact:boots-side", "alt": "Side view"}]}
```

Without `options`, a product has Shopify's single `Title` / `Default Title` option and at most one
variant. With `options`, every variant names one value for each option in `option_values`; without
`variants`, the one variant Shopify would build from the first value of each option is created.
Up to 100 variants per call: every one is confirmed in the same answer, which is bounded by
Shopify's query cost limit. `product_variants` returns every created variant with its inventory
item, ready for later stock or price steps.

Images reach a product three ways:

- `media`: a public HTTPS URL Shopify downloads (images, videos, 3D models; YouTube or Vimeo for
  `EXTERNAL_VIDEO`), or the id of a file already in Shopify Files.
- `image_files`: a Flow Steward artifact — a JPEG, PNG, GIF or WEBP of up to 20 MB, up to 20 per
  call. The extension reads it, checks its file signature, stages it with Shopify's
  `stagedUploadsCreate`, uploads it to Shopify's own storage host and attaches it. Staging changes
  nothing in the store; a failure before the product mutation leaves no product behind.
- `update_product` accepts the same `media` (by URL) and `image_files` to add images to an
  existing product.

Product creation success does not mean every image is processed. Use `list_product_media` and
its `status`, `media_errors`, `image.width` and `image.height` after processing. Shopify
recommends 2048 × 2048 product images; this extension does not crop, pad or upscale. See
[Shopify productSet](https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/productSet).

## Bulk creation of new products

`create_products_bulk` submits a batch for asynchronous Shopify processing. Supply exactly one:

- `products`: 1–10000 objects with the same fields as `create_product`, without `connection_ref` and `image_files` per row.
- `artifact_handle`: a UTF-8 JSONL artifact, one such object per line, up to 10000 rows and 100 MB.

Every row requires `title` and `handle`. All rows are validated before contacting Shopify;
duplicate handles within the batch are refused. Each row runs Shopify's `productSet`, so it can
carry its variants, SKUs, prices, stock and media URLs exactly as `create_product` does.

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
`runtime/documents.py`, plus the fixed internal documents for bulk staging and rows, export
relations and image staging. Nothing is interpolated into them; every caller value travels as a
GraphQL variable, including the SKU search string, which is built inside the extension. Each
record a document selects is declared once as a table of Shopify fields in `runtime/records.py`,
from which the published schema and the result shaper both come.

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
`tracked: false`, zero cost, and a separate price change remain valid. A new product's variants
must name one value for each of its options, without repeating a combination. These checks
refuse invalid input before any outbound request.

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

`create_product` returns the `product` and `product_variants`, every variant it created, each with
its product id and `inventory_item.id`, so a workflow can map them to later
`update_product_variants_batch` or `set_inventory_quantities` steps without a store-wide lookup.

`list_locations` and `list_inventory_items` return one page and the cursor for the next one. They do
not auto-paginate: pass `page_info.end_cursor` back as `after`.

`get_inventory_levels_batch` preserves the order of `inventory_item_ids` and answers for every id it
was given. An id Shopify cannot resolve comes back with `found: false`; an item that is simply not
stocked at that location comes back with `level: null`. Neither is an operation failure — losing a
batch of 250 because one id was retired would be the worse outcome.

`set_inventory_quantities` writes absolute quantities — `available` by default, or `on_hand` — with
Shopify's `reason` code (`correction` by default) and a
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

`--version 2026-07` selects the toolkit's bundled public schema, which is also the reference for
`tests/reference/admin_schema_2026_07.json`.

| Document | Artifact id | Revision | API version | Result |
|---|---|---:|---|---|
| `test_connection` | `fs-shopify-040-test-connection` | 1 | `2026-07` | ✅ VALID |
| `get_shop` | `fs-shopify-040-get-shop` | 1 | `2026-07` | ✅ VALID |
| `list_locations` | `fs-shopify-040-list-locations` | 1 | `2026-07` | ✅ VALID |
| `list_inventory_items` | `fs-shopify-040-list-inventory-items` | 1 | `2026-07` | ✅ VALID |
| `get_inventory_item` | `fs-shopify-040-get-inventory-item` | 1 | `2026-07` | ✅ VALID |
| `get_inventory_levels_batch` | `fs-shopify-040-get-inventory-levels-batch` | 1 | `2026-07` | ✅ VALID |
| `set_inventory_quantities` | `fs-shopify-040-set-inventory-quantities` | 1 | `2026-07` | ✅ VALID |
| `list_products` | `fs-shopify-040-list-products` | 1 | `2026-07` | ✅ VALID |
| `export_products` | `fs-shopify-040-export-products` | 1 | `2026-07` | ✅ VALID |
| `create_products_bulk` | `fs-bulk-products-040-submit` | 1 | `2026-07` | ✅ VALID |
| `get_product` | `fs-shopify-040-get-product` | 1 | `2026-07` | ✅ VALID |
| `list_product_variants` | `fs-shopify-040-list-product-variants` | 1 | `2026-07` | ✅ VALID |
| `get_product_variant` | `fs-shopify-040-get-product-variant` | 1 | `2026-07` | ✅ VALID |
| `list_catalog_metafields` | `fs-shopify-040-list-catalog-metafields` | 1 | `2026-07` | ✅ VALID |
| `list_product_media` | `fs-shopify-040-list-product-media` | 1 | `2026-07` | ✅ VALID |
| `create_product` | `fs-shopify-040-create-product` | 1 | `2026-07` | ✅ VALID |
| `update_product` | `fs-shopify-040-update-product` | 1 | `2026-07` | ✅ VALID |
| `create_product_variants_batch` | `fs-shopify-040-create-product-variants-batch` | 1 | `2026-07` | ✅ VALID |
| `update_product_variants_batch` | `fs-shopify-040-update-product-variants-batch` | 1 | `2026-07` | ✅ VALID |
| `set_catalog_metafields` | `fs-shopify-040-set-catalog-metafields` | 1 | `2026-07` | ✅ VALID |
| `update_product_media` | `fs-shopify-040-update-product-media` | 1 | `2026-07` | ✅ VALID |
| `list_orders` | `fs-shopify-040-list-orders` | 1 | `2026-07` | ✅ VALID |
| `get_order` | `fs-shopify-040-get-order` | 1 | `2026-07` | ✅ VALID |
| `list_order_line_items` | `fs-shopify-040-list-order-line-items` | 1 | `2026-07` | ✅ VALID |
| `list_order_metafields` | `fs-shopify-040-list-order-metafields` | 1 | `2026-07` | ✅ VALID |
| `list_order_fulfillment_orders` | `fs-shopify-040-list-order-fulfillment-orders` | 1 | `2026-07` | ✅ VALID |
| `get_fulfillment_order` | `fs-shopify-040-get-fulfillment-order` | 1 | `2026-07` | ✅ VALID |
| `list_order_fulfillments` | `fs-shopify-040-list-order-fulfillments` | 1 | `2026-07` | ✅ VALID |
| `update_order_metadata` | `fs-shopify-040-update-order-metadata` | 1 | `2026-07` | ✅ VALID |
| `set_order_metafields` | `fs-shopify-040-set-order-metafields` | 1 | `2026-07` | ✅ VALID |
| `create_fulfillment` | `fs-shopify-040-create-fulfillment` | 1 | `2026-07` | ✅ VALID |
| `update_fulfillment_tracking` | `fs-shopify-040-update-fulfillment-tracking` | 1 | `2026-07` | ✅ VALID |

The fixed internal documents passed the same validation at revision 1: `bulk_documents.STAGE` (`fs-shopify-040-bulk-documents-stage`), `bulk_documents.CREATE_ROW` (`fs-shopify-040-bulk-documents-create-row`), `export_documents.IMAGES` (`fs-shopify-040-export-documents-images`), `export_documents.VARIANTS` (`fs-shopify-040-export-documents-variants`), `export_documents.INVENTORY` (`fs-shopify-040-export-documents-inventory`), `media_documents.STAGE_IMAGES` (`fs-shopify-040-media-documents-stage-images`). Callers cannot supply or change any of them.

All documents were revalidated for 0.4.0 against the Shopify AI Toolkit's bundled public `2026-07` schema. Two fields the shopify.dev introspection proxy reports — `ProductOption.createdAt` and `LineItem.createdAt` — are absent from that public schema and are therefore not selected.

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
runtime/catalog.py              the 33 declared operations, with their own schemas
runtime/inputs.py               input schema fragments mirroring Shopify's input objects
runtime/product_input.py        input -> Shopify variables, field by field
runtime/records.py              every returned record as a table of Shopify fields
runtime/coverage.py             what of the official API is deliberately not reachable, and why
runtime/documents.py            the 32 public GraphQL documents, and nothing else
runtime/media_upload.py         artifact images through Shopify's staged upload
runtime/catalog_quality.py      the export's catalog-quality checks
runtime/schema.py               executes the published input schema
runtime/validation.py           id typing, semantic rules, defaults, runtime context
runtime/connection.py           domain normalization, secret handling, endpoint derivation
runtime/transport.py            one POST to one URL, over the public SDK
runtime/operations.py           one handler per operation
runtime/errors.py               the stable error vocabulary and the Shopify mappings
tests/reference/                offline generators, and the pinned official schema slice
ui/                             connection form, setup guide, operations, API coverage, changelog
```

## Tests

Every test runs offline against mocked Shopify responses. No production credential and no live store
is needed, and none is referenced.

```bash
python -m pytest tests -q
```

Regenerate the contracts and the generated pages after changing the registry:

```bash
python tests/reference/refresh_contracts.py
```

After changing a document, regenerate the pinned schema slice from the Shopify AI Toolkit's public
schema and rerun the tests:

```bash
python tests/reference/admin_schema.py path/to/admin_2026-07.json.gz
```
