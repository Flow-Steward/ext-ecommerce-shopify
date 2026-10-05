"""What of Shopify's official API this extension deliberately does not expose, and why.

The rule is complete coverage of every endpoint the extension uses: every input
field of every mutation it sends, every argument of every list it reads, and
every scalar and money field of every record it returns. Anything outside that
is listed here with the reason, so a user can see exactly what is and is not
possible, and ``tests/test_admin_api_coverage.py`` fails if Shopify's schema
offers a field that is neither covered nor listed.

Paths are dotted, starting at the mutation argument: ``input.variants.id`` is the
``id`` field of each element of the ``variants`` list inside the ``input``
argument. Excluding a path excludes everything beneath it.
"""

from __future__ import annotations

_NEW_RECORD = "A record being created has no id of its own yet."
_BY_NAME = "Option values are named by option name and value, which identifies them fully."
_SKU_ON_VARIANT = (
    "SKU is set on the variant itself; Shopify accepts the same value in either place."
)
_TRACKING_LISTS = "Use numbers and urls: they carry the same values as lists."

#: Mutation input paths a caller cannot set, per operation.
INPUT_EXCLUSIONS: dict[str, dict[str, str]] = {
    "create_product": {
        "synchronous": "Fixed to true: the operation waits for Shopify and returns the "
        "product it created, rather than an asynchronous job id.",
        "identifier": "Creating never updates an existing product by mistake; change an "
        "existing product with update_product.",
        "input.redirectNewHandle": "Applies only when an existing product's handle changes; "
        "see update_product.redirect_new_handle.",
        "input.productOptions.id": _NEW_RECORD,
        "input.productOptions.values.id": _NEW_RECORD,
        "input.variants.id": _NEW_RECORD,
        "input.variants.optionValues.id": _NEW_RECORD,
        "input.variants.optionValues.optionId": _NEW_RECORD,
        "input.variants.inventoryItem.sku": _SKU_ON_VARIANT,
        "input.metafields.id": _NEW_RECORD,
        "input.variants.metafields.id": _NEW_RECORD,
    },
    "create_products_bulk": {
        "identifier": "Bulk creation only creates; it never updates an existing product.",
        "input.redirectNewHandle": "Applies only when an existing product's handle changes.",
        "input.productOptions.id": _NEW_RECORD,
        "input.productOptions.values.id": _NEW_RECORD,
        "input.variants.id": _NEW_RECORD,
        "input.variants.optionValues.id": _NEW_RECORD,
        "input.variants.optionValues.optionId": _NEW_RECORD,
        "input.variants.inventoryItem.sku": _SKU_ON_VARIANT,
        "input.metafields.id": _NEW_RECORD,
        "input.variants.metafields.id": _NEW_RECORD,
        "synchronous": "Inside a bulk operation Shopify runs every row synchronously.",
    },
    "update_product": {
        "identifier.id": "Name the product by id with product_id.",
    },
    "create_product_variants_batch": {
        "variants.id": _NEW_RECORD,
        "variants.optionValues.id": _BY_NAME,
        "variants.optionValues.optionId": _BY_NAME,
    },
    "update_product_variants_batch": {
        "variants.optionValues.id": _BY_NAME,
        "variants.optionValues.optionId": _BY_NAME,
    },
    "set_inventory_quantities": {
        "input.referenceDocumentUri": "Always this run's external effect, so every "
        "adjustment in Shopify traces back to the workflow run that made it.",
    },
    "create_fulfillment": {
        "fulfillment.trackingInfo.number": _TRACKING_LISTS,
        "fulfillment.trackingInfo.url": _TRACKING_LISTS,
    },
    "update_fulfillment_tracking": {
        "trackingInfoInput.number": _TRACKING_LISTS,
        "trackingInfoInput.url": _TRACKING_LISTS,
    },
}

_FORWARD_ONLY = "Pages are read forwards with first and after."
_ONE_PAGE = "The nested list is read as one bounded page."

#: Arguments of selected fields that no caller sets: ``"Type.field": {argument: reason}``.
#: ``before`` and ``last`` are never offered anywhere — pages are read forwards.
GLOBAL_ARGUMENT_EXCLUSIONS: dict[str, str] = {
    "before": _FORWARD_ONLY,
    "last": _FORWARD_ONLY,
}

ARGUMENT_EXCLUSIONS: dict[str, dict[str, str]] = {
    "Product.variants": {
        "after": "create_product confirms every variant it created in one page; "
        "list_product_variants pages through variants.",
        "reverse": _ONE_PAGE,
        "sortKey": _ONE_PAGE,
    },
    "Product.options": {"first": "A product has at most three options; all are returned."},
    "Product.media": {"reverse": "export_products reads images in their display order."},
    "Fulfillment.trackingInfo": {"first": "Bounded to the first 10 tracking entries."},
    "Order.fulfillmentsCount": {
        "limit": "The exact count is wanted, so no upper limit is applied.",
        "query": "Counts every fulfillment, so a truncated list can be detected.",
    },
    "InventoryItem.inventoryLevels": {
        "reverse": _ONE_PAGE,
        "query": _ONE_PAGE,
        "includeInactive": "export_products reports the locations an item is stocked at.",
    },
    "FulfillmentOrder.lineItems": {
        "reverse": "Line items keep Shopify's own order.",
        "after": "list_order_fulfillment_orders returns one page of line items per "
        "fulfillment order; get_fulfillment_order pages through them.",
    },
    "Product.description": {"truncateAt": "The whole plain-text description is returned."},
    "Order.statusPageUrl": {
        "audience": "Shopify's default order status page URL is returned.",
        "notificationUsage": "Shopify's default order status page URL is returned.",
    },
    "LineItem.discountedTotalSet": {"withCodeDiscounts": "Read with Shopify's default."},
    "Image.url": {"transform": "The original image URL is returned, never a resized copy."},
    "InventoryAdjustmentGroup.changes": {
        "inventoryItemIds": "Every change of the adjustment is returned, unfiltered.",
        "locationIds": "Every change of the adjustment is returned, unfiltered.",
        "quantityNames": "Every change of the adjustment is returned, unfiltered.",
    },
    "InventoryLevel.quantities": {
        "names": "Every quantity state is always read.",
    },
}

_PROTECTED = (
    "Protected customer data. Selecting it makes Shopify refuse the whole request for an "
    "app without that access, so it is never read."
)

#: Record fields the official schema offers that results never carry.
FIELD_EXCLUSIONS: dict[str, dict[str, str]] = {
    "PageInfo": {
        "hasPreviousPage": "Pages are read forwards with first and after.",
        "startCursor": "Pages are read forwards with first and after.",
    },
    "Shop": {
        "email": "The store owner's personal email address.",
        "shopOwnerName": "The store owner's personal name.",
    },
    "Order": {
        "email": _PROTECTED,
        "phone": _PROTECTED,
        "clientIp": "The customer's IP address: personal data that no workflow step needs.",
    },
    "Product": {"defaultCursor": "A pagination cursor; use page_info.end_cursor."},
    "ProductVariant": {"defaultCursor": "A pagination cursor; use page_info.end_cursor."},
}

#: Money is read in the shop's currency.
MONEY_NOTE = (
    "Money fields carry the shop-currency amount (MoneyBag.shopMoney); the presentment "
    "currency amount is not read."
)

__all__ = [
    "ARGUMENT_EXCLUSIONS",
    "FIELD_EXCLUSIONS",
    "GLOBAL_ARGUMENT_EXCLUSIONS",
    "INPUT_EXCLUSIONS",
    "MONEY_NOTE",
]
