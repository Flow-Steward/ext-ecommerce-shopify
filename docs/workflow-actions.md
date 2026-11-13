# Shopify workflow actions

Configure the Shopify app in the extension's **Setup Guide**: save its Client ID
and secret, register this project's exact OAuth callback URL and release an app
version with the configured eight-scope set. Add a project connection for the
`myshopify.com` store and complete OAuth authorization. Select that connection
on every action and run **Test the connection**. This extension uses the fixed
Admin GraphQL 2026-07 operations described in the in-app Inventory API page.

Examples below use existing action IDs and input names. Replace example GIDs
with IDs read from the selected store. A product ID, variant ID, inventory item
ID, location ID and fulfillment-order ID identify different things.

## Create a product, then update it

Choose **Create a product** (`create_product`) and set:

```json
{"title":"Blue ceramic mug","handle":"blue-ceramic-mug","description_html":"<p>Glazed ceramic mug, 300 ml.</p>","status":"DRAFT"}
```

The handle must be unused. A new product defaults to DRAFT. You can also supply
options, variants, prices, starting stock, metafields and media using the nested
fields declared in this action's schema. To add a public image, use **Media**:

```json
[{"source_url":"https://example.com/blue-mug.jpg","content_type":"IMAGE","alt":"Blue ceramic mug"}]
```

Replace the URL with an image your store can fetch. Media processing is
asynchronous; **List product media** reports readiness and errors.

Bind the returned product ID into **Update a product** (`update_product`) to
change supplied product fields. Use **Create product variants** or **Update
product variants** for variant batches. Match each action's variant schema:
creating whole products and creating variants have different stock-input shapes.
For larger imports, **Create products in bulk** submits work asynchronously;
submission success is not confirmation that every row was created. See the bulk
product submission decision document for reconciliation limits.

## Set stock at a location

1. Read the inventory item ID from product variants or **List inventory items**.
   Read the location ID using **List locations**.
2. Use **Get stock for many items at one location** (`get_inventory_levels_batch`) to read the
   current quantity for the item and location.
3. Choose **Set stock quantities** (`set_inventory_quantities`). Set **Quantity
   state** to `available` and **Quantities** to:

   ```json
   [{"inventory_item_id":"gid://shopify/InventoryItem/3042","location_id":"gid://shopify/Location/4042","quantity":24,"change_from_quantity":18}]
   ```

   Replace the IDs and 18 with the values you just read. This sets the absolute
   count to 24. `change_from_quantity` lets Shopify reject a conflicting change;
   explicitly passing null writes regardless of the previous count. Zero makes
   the item out of stock at that location. Inspect the returned adjustment group.

## Read, export and improve the catalog

**List products** returns one cursor page. For example, set **Shopify search
query** to `status:active`, **Page size** to 10 and leave **After cursor** empty.
When `result.page_info.has_next_page` is true, bind its `end_cursor` into **After
cursor** and continue with the same filters. Other cursor lists follow this
pattern; page-size limits differ by action.

**Export all matching products** (`export_products`) reads all matching pages and writes a
JSONL file. Select quality filters when building a queue for missing images,
small images, missing alt text, short descriptions or missing catalog fields.
Bind the returned file handle into downstream file processing. List and export
filters select records; they do not fix those records.

## Work on orders and fulfillment

Read orders with **List orders** or **Get an order**. Use order-line and
fulfillment-order lists to obtain the IDs and quantities for a fulfillment;
order line IDs and fulfillment-order line IDs are different. **Create a
fulfillment** requires explicit fulfillment orders and line items, for example:

```json
[{"fulfillment_order_id":"gid://shopify/FulfillmentOrder/6042","line_items":[{"fulfillment_order_line_item_id":"gid://shopify/FulfillmentOrderLineItem/8042","quantity":1}]}]
```

Bind real IDs and fulfillable quantities from the read steps. Review tracking
and customer-notification settings before running it. **Update fulfillment
tracking** changes tracking on an existing fulfillment. Order metadata and
metafield actions change their declared fields; this release does not cancel
orders or create refunds.

Write actions are suppressed in test mode. After an unknown write outcome,
read the affected Shopify record before repeating the change. See the in-app
Inventory API page for each action's exact inputs and required permissions.
