"""Every record this extension returns, declared once as a table of Shopify fields.

One table per Shopify type. Each row names the Shopify field, the key it is
published under and how its value is carried. From the same table come the
published JSON Schema (:func:`schema`) and the shaper that turns Shopify's
answer into that record (:func:`shape`). The fixed GraphQL documents in
:mod:`runtime.documents` stay literal text; ``tests/test_admin_api_coverage.py``
proves each document selects exactly the fields its table declares, and that
each table carries every field the official schema offers apart from the ones
:mod:`runtime.coverage` excludes with a stated reason.

Shapers are total: every declared key is present whatever Shopify sent, filled
with ``None`` when absent, because a workflow binds to a key and a key that
appears only when the store populated it breaks on the second record.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: A page of nested records is bounded by the page size asked for; this is the
#: ceiling for a nested list nobody paginates.
MAX_NESTED_ITEMS = 250


@dataclass(frozen=True)
class Field:
    """One Shopify field and how this extension publishes it.

    ``kind`` is one of:

    * ``id`` — the record's own id, always a string;
    * ``text``, ``int``, ``number``, ``bool``, ``json`` — one scalar, ``None`` when absent;
    * ``list_text`` — a list of strings;
    * ``money`` — a ``MoneyBag``, published as its shop-currency amount;
    * ``ref`` — a related record published only as its id;
    * ``record`` / ``records`` — a nested record, or a list of them, of type ``target``;
    * ``connection`` — a paginated list of ``target`` records, published as the
      list under ``key`` and its page info under ``key + "_page_info"``.

    ``on`` names the concrete type an inline fragment selects the field from.
    """

    graphql: str
    key: str
    kind: str
    target: str = ""
    on: str = ""


def _f(graphql: str, key: str, kind: str, target: str = "", on: str = "") -> Field:
    return Field(graphql, key, kind, target, on)


MONEY_V2 = "MoneyV2"

RECORDS: dict[str, tuple[Field, ...]] = {
    "MoneyV2": (_f("amount", "amount", "text"), _f("currencyCode", "currency_code", "text")),
    "PageInfo": (
        _f("hasNextPage", "has_next_page", "bool"),
        _f("endCursor", "end_cursor", "text"),
    ),
    "Shop": (
        _f("id", "id", "id"),
        _f("name", "name", "text"),
        _f("myshopifyDomain", "myshopify_domain", "text"),
        _f("currencyCode", "currency_code", "text"),
        _f("ianaTimezone", "iana_timezone", "text"),
        _f("checkoutApiSupported", "checkout_api_supported", "bool"),
        _f("contactEmail", "contact_email", "text"),
        _f("createdAt", "created_at", "text"),
        _f("customerAccounts", "customer_accounts", "text"),
        _f("description", "description", "text"),
        _f("enabledPresentmentCurrencies", "enabled_presentment_currencies", "list_text"),
        _f(
            "marketingSmsConsentEnabledAtCheckout",
            "marketing_sms_consent_enabled_at_checkout",
            "bool",
        ),
        _f("orderNumberFormatPrefix", "order_number_format_prefix", "text"),
        _f("orderNumberFormatSuffix", "order_number_format_suffix", "text"),
        _f("richTextEditorUrl", "rich_text_editor_url", "text"),
        _f("setupRequired", "setup_required", "bool"),
        _f("shipsToCountries", "ships_to_countries", "list_text"),
        _f("taxShipping", "tax_shipping", "bool"),
        _f("taxesIncluded", "taxes_included", "bool"),
        _f("timezoneAbbreviation", "timezone_abbreviation", "text"),
        _f("timezoneOffset", "timezone_offset", "text"),
        _f("timezoneOffsetMinutes", "timezone_offset_minutes", "int"),
        _f("transactionalSmsDisabled", "transactional_sms_disabled", "bool"),
        _f("unitSystem", "unit_system", "text"),
        _f("updatedAt", "updated_at", "text"),
        _f("url", "url", "text"),
        _f("weightUnit", "weight_unit", "text"),
    ),
    "Location": (
        _f("id", "id", "id"),
        _f("name", "name", "text"),
        _f("isActive", "is_active", "bool"),
        _f("fulfillsOnlineOrders", "fulfills_online_orders", "bool"),
        _f("shipsInventory", "ships_inventory", "bool"),
        _f("activatable", "activatable", "bool"),
        _f("addressVerified", "address_verified", "bool"),
        _f("createdAt", "created_at", "text"),
        _f("deactivatable", "deactivatable", "bool"),
        _f("deactivatedAt", "deactivated_at", "text"),
        _f("deletable", "deletable", "bool"),
        _f("hasActiveInventory", "has_active_inventory", "bool"),
        _f("hasUnfulfilledOrders", "has_unfulfilled_orders", "bool"),
        _f("isFulfillmentService", "is_fulfillment_service", "bool"),
        _f("legacyResourceId", "legacy_resource_id", "text"),
        _f("updatedAt", "updated_at", "text"),
    ),
    "Weight": (_f("unit", "unit", "text"), _f("value", "value", "number")),
    "InventoryItemMeasurement": (
        _f("id", "id", "text"),
        _f("weight", "weight", "record", "Weight"),
    ),
    "InventoryItem": (
        _f("id", "id", "id"),
        _f("sku", "sku", "text"),
        _f("tracked", "tracked", "bool"),
        _f("requiresShipping", "requires_shipping", "bool"),
        _f("updatedAt", "updated_at", "text"),
        _f("countryCodeOfOrigin", "country_code_of_origin", "text"),
        _f("createdAt", "created_at", "text"),
        _f("duplicateSkuCount", "duplicate_sku_count", "int"),
        _f("harmonizedSystemCode", "harmonized_system_code", "text"),
        _f("inventoryHistoryUrl", "inventory_history_url", "text"),
        _f("legacyResourceId", "legacy_resource_id", "text"),
        _f("provinceCodeOfOrigin", "province_code_of_origin", "text"),
        _f("unitCost", "unit_cost", "record", MONEY_V2),
        _f("measurement", "measurement", "record", "InventoryItemMeasurement"),
    ),
    "SEO": (_f("title", "title", "text"), _f("description", "description", "text")),
    "ProductOption": (
        _f("id", "id", "id"),
        _f("name", "name", "text"),
        _f("position", "position", "int"),
        _f("values", "values", "list_text"),
    ),
    "Product": (
        _f("id", "id", "id"),
        _f("title", "title", "text"),
        _f("handle", "handle", "text"),
        _f("descriptionHtml", "description_html", "text"),
        _f("description", "description", "text"),
        _f("vendor", "vendor", "text"),
        _f("productType", "product_type", "text"),
        _f("status", "status", "text"),
        _f("tags", "tags", "list_text"),
        _f("category", "category_id", "ref"),
        _f("seo", "seo", "record", "SEO"),
        _f("createdAt", "created_at", "text"),
        _f("updatedAt", "updated_at", "text"),
        _f("publishedAt", "published_at", "text"),
        _f("options", "options", "records", "ProductOption"),
        _f("combinedListingRole", "combined_listing_role", "text"),
        _f("giftCardTemplateSuffix", "gift_card_template_suffix", "text"),
        _f("hasOnlyDefaultVariant", "has_only_default_variant", "bool"),
        _f("hasOutOfStockVariants", "has_out_of_stock_variants", "bool"),
        _f(
            "hasVariantsThatRequiresComponents",
            "has_variants_that_requires_components",
            "bool",
        ),
        _f("isGiftCard", "is_gift_card", "bool"),
        _f("legacyResourceId", "legacy_resource_id", "text"),
        _f("onlineStorePreviewUrl", "online_store_preview_url", "text"),
        _f("onlineStoreUrl", "online_store_url", "text"),
        _f("requiresSellingPlan", "requires_selling_plan", "bool"),
        _f("templateSuffix", "template_suffix", "text"),
        _f("totalInventory", "total_inventory", "int"),
        _f("tracksInventory", "tracks_inventory", "bool"),
    ),
    "SelectedOption": (_f("name", "name", "text"), _f("value", "value", "text")),
    "UnitPriceMeasurement": (
        _f("measuredType", "measured_type", "text"),
        _f("quantityUnit", "quantity_unit", "text"),
        _f("quantityValue", "quantity_value", "number"),
        _f("referenceUnit", "reference_unit", "text"),
        _f("referenceValue", "reference_value", "int"),
    ),
    "ProductVariant": (
        _f("id", "id", "id"),
        _f("product", "product_id", "ref"),
        _f("title", "title", "text"),
        _f("displayName", "display_name", "text"),
        _f("sku", "sku", "text"),
        _f("barcode", "barcode", "text"),
        _f("position", "position", "int"),
        _f("price", "price", "text"),
        _f("compareAtPrice", "compare_at_price", "text"),
        _f("unitPrice", "unit_price", "record", MONEY_V2),
        _f("showUnitPrice", "show_unit_price", "bool"),
        _f("unitPriceMeasurement", "unit_price_measurement", "record", "UnitPriceMeasurement"),
        _f("inventoryPolicy", "inventory_policy", "text"),
        _f("inventoryQuantity", "inventory_quantity", "int"),
        _f("sellableOnlineQuantity", "sellable_online_quantity", "int"),
        _f("availableForSale", "available_for_sale", "bool"),
        _f("taxable", "taxable", "bool"),
        _f("requiresComponents", "requires_components", "bool"),
        _f("legacyResourceId", "legacy_resource_id", "text"),
        _f("createdAt", "created_at", "text"),
        _f("updatedAt", "updated_at", "text"),
        _f("selectedOptions", "selected_options", "records", "SelectedOption"),
        _f("inventoryItem", "inventory_item", "record", "InventoryItem"),
    ),
    "Metafield": (
        _f("id", "id", "id"),
        _f("namespace", "namespace", "text"),
        _f("key", "key", "text"),
        _f("type", "type", "text"),
        _f("value", "value", "text"),
        _f("jsonValue", "json_value", "json"),
        _f("compareDigest", "compare_digest", "text"),
        _f("ownerType", "owner_type", "text"),
        _f("sizeInBytes", "size_in_bytes", "int"),
        _f("legacyResourceId", "legacy_resource_id", "text"),
        _f("createdAt", "created_at", "text"),
        _f("updatedAt", "updated_at", "text"),
    ),
    "Image": (
        _f("id", "id", "text"),
        _f("url", "url", "text"),
        _f("altText", "alt_text", "text"),
        _f("width", "width", "int"),
        _f("height", "height", "int"),
        _f("thumbhash", "thumbhash", "text"),
    ),
    "MediaPreviewImage": (
        _f("status", "status", "text"),
        _f("image", "image", "record", "Image"),
    ),
    "MediaError": (
        _f("code", "code", "text"),
        _f("details", "details", "text"),
        _f("message", "message", "text"),
    ),
    "MediaWarning": (_f("code", "code", "text"), _f("message", "message", "text")),
    #: Product media is a Shopify interface. The interface's own fields come
    #: first; each concrete type's extra fields are selected through a fragment
    #: and are ``None`` on the other types.
    "Media": (
        _f("id", "id", "id"),
        _f("mediaContentType", "media_content_type", "text"),
        _f("alt", "alt", "text"),
        _f("status", "status", "text"),
        _f("preview", "preview", "record", "MediaPreviewImage"),
        _f("mediaErrors", "media_errors", "records", "MediaError"),
        _f("mediaWarnings", "media_warnings", "records", "MediaWarning"),
        _f("createdAt", "created_at", "text", on="MediaImage"),
        _f("updatedAt", "updated_at", "text", on="MediaImage"),
        _f("fileStatus", "file_status", "text", on="MediaImage"),
        _f("mimeType", "mime_type", "text", on="MediaImage"),
        _f("image", "image", "record", "Image", on="MediaImage"),
        _f("createdAt", "created_at", "text", on="Video"),
        _f("updatedAt", "updated_at", "text", on="Video"),
        _f("fileStatus", "file_status", "text", on="Video"),
        _f("filename", "filename", "text", on="Video"),
        _f("duration", "duration", "int", on="Video"),
        _f("createdAt", "created_at", "text", on="Model3d"),
        _f("updatedAt", "updated_at", "text", on="Model3d"),
        _f("fileStatus", "file_status", "text", on="Model3d"),
        _f("filename", "filename", "text", on="Model3d"),
        _f("createdAt", "created_at", "text", on="ExternalVideo"),
        _f("updatedAt", "updated_at", "text", on="ExternalVideo"),
        _f("fileStatus", "file_status", "text", on="ExternalVideo"),
        _f("embedUrl", "embed_url", "text", on="ExternalVideo"),
        _f("host", "host", "text", on="ExternalVideo"),
        _f("originUrl", "origin_url", "text", on="ExternalVideo"),
    ),
    "FileError": (
        _f("code", "code", "text"),
        _f("details", "details", "text"),
        _f("message", "message", "text"),
    ),
    #: A file in Shopify Files, as ``fileUpdate`` confirms it. Like product
    #: media this is an interface; concrete fields come through fragments.
    "File": (
        _f("id", "id", "id"),
        _f("alt", "alt", "text"),
        _f("fileStatus", "file_status", "text"),
        _f("createdAt", "created_at", "text"),
        _f("updatedAt", "updated_at", "text"),
        _f("preview", "preview", "record", "MediaPreviewImage"),
        _f("fileErrors", "file_errors", "records", "FileError"),
        _f("mediaContentType", "media_content_type", "text", on="MediaImage"),
        _f("status", "status", "text", on="MediaImage"),
        _f("mimeType", "mime_type", "text", on="MediaImage"),
        _f("image", "image", "record", "Image", on="MediaImage"),
        _f("mediaContentType", "media_content_type", "text", on="Video"),
        _f("status", "status", "text", on="Video"),
        _f("filename", "filename", "text", on="Video"),
        _f("duration", "duration", "int", on="Video"),
        _f("mediaContentType", "media_content_type", "text", on="Model3d"),
        _f("status", "status", "text", on="Model3d"),
        _f("filename", "filename", "text", on="Model3d"),
        _f("mediaContentType", "media_content_type", "text", on="ExternalVideo"),
        _f("status", "status", "text", on="ExternalVideo"),
        _f("embedUrl", "embed_url", "text", on="ExternalVideo"),
        _f("host", "host", "text", on="ExternalVideo"),
        _f("originUrl", "origin_url", "text", on="ExternalVideo"),
        _f("mimeType", "mime_type", "text", on="GenericFile"),
        _f("url", "url", "text", on="GenericFile"),
        _f("originalFileSize", "original_file_size", "int", on="GenericFile"),
    ),
    "Attribute": (_f("key", "key", "text"), _f("value", "value", "text")),
    "Order": (
        _f("id", "id", "id"),
        _f("name", "name", "text"),
        _f("number", "number", "int"),
        _f("confirmationNumber", "confirmation_number", "text"),
        _f("legacyResourceId", "legacy_resource_id", "text"),
        _f("createdAt", "created_at", "text"),
        _f("updatedAt", "updated_at", "text"),
        _f("processedAt", "processed_at", "text"),
        _f("cancelledAt", "cancelled_at", "text"),
        _f("cancelReason", "cancel_reason", "text"),
        _f("closedAt", "closed_at", "text"),
        _f("closed", "closed", "bool"),
        _f("confirmed", "confirmed", "bool"),
        _f("test", "test", "bool"),
        _f("edited", "edited", "bool"),
        _f("displayFinancialStatus", "display_financial_status", "text"),
        _f("displayFulfillmentStatus", "display_fulfillment_status", "text"),
        _f("returnStatus", "return_status", "text"),
        _f("currencyCode", "currency_code", "text"),
        _f("presentmentCurrencyCode", "presentment_currency_code", "text"),
        _f("tags", "tags", "list_text"),
        _f("note", "note", "text"),
        _f("poNumber", "po_number", "text"),
        _f("customAttributes", "custom_attributes", "records", "Attribute"),
        _f("sourceName", "source_name", "text"),
        _f("sourceIdentifier", "source_identifier", "text"),
        _f("registeredSourceUrl", "registered_source_url", "text"),
        _f("statusPageUrl", "status_page_url", "text"),
        _f("cartToken", "cart_token", "text"),
        _f("checkoutToken", "checkout_token", "text"),
        _f("customerLocale", "customer_locale", "text"),
        _f("customerAcceptsMarketing", "customer_accepts_marketing", "bool"),
        _f("discountCode", "discount_code", "text"),
        _f("discountCodes", "discount_codes", "list_text"),
        _f("paymentGatewayNames", "payment_gateway_names", "list_text"),
        _f(
            "billingAddressMatchesShippingAddress",
            "billing_address_matches_shipping_address",
            "bool",
        ),
        _f("canMarkAsPaid", "can_mark_as_paid", "bool"),
        _f("canNotifyCustomer", "can_notify_customer", "bool"),
        _f("capturable", "capturable", "bool"),
        _f("fulfillable", "fulfillable", "bool"),
        _f("fullyPaid", "fully_paid", "bool"),
        _f("unpaid", "unpaid", "bool"),
        _f("refundable", "refundable", "bool"),
        _f("restockable", "restockable", "bool"),
        _f("requiresShipping", "requires_shipping", "bool"),
        _f("merchantEditable", "merchant_editable", "bool"),
        _f("merchantEditableErrors", "merchant_editable_errors", "list_text"),
        _f("hasTimelineComment", "has_timeline_comment", "bool"),
        _f("productNetwork", "product_network", "bool"),
        _f("dutiesIncluded", "duties_included", "bool"),
        _f("estimatedTaxes", "estimated_taxes", "bool"),
        _f("taxExempt", "tax_exempt", "bool"),
        _f("taxesIncluded", "taxes_included", "bool"),
        _f("subtotalLineItemsQuantity", "subtotal_line_items_quantity", "int"),
        _f("currentSubtotalLineItemsQuantity", "current_subtotal_line_items_quantity", "int"),
        _f("totalWeight", "total_weight", "text"),
        _f("currentTotalWeight", "current_total_weight", "text"),
        _f("totalPriceSet", "total_price", "money"),
        _f("subtotalPriceSet", "subtotal_price", "money"),
        _f("totalTaxSet", "total_tax", "money"),
        _f("totalShippingPriceSet", "total_shipping_price", "money"),
        _f("totalDiscountsSet", "total_discounts", "money"),
        _f("cartDiscountAmountSet", "cart_discount_amount", "money"),
        _f("currentCartDiscountAmountSet", "current_cart_discount_amount", "money"),
        _f("currentShippingPriceSet", "current_shipping_price", "money"),
        _f("currentSubtotalPriceSet", "current_subtotal_price", "money"),
        _f("currentTotalAdditionalFeesSet", "current_total_additional_fees", "money"),
        _f("currentTotalDiscountsSet", "current_total_discounts", "money"),
        _f("currentTotalDutiesSet", "current_total_duties", "money"),
        _f("currentTotalPriceSet", "current_total_price", "money"),
        _f("currentTotalTaxSet", "current_total_tax", "money"),
        _f("netPaymentSet", "net_payment", "money"),
        _f("originalTotalAdditionalFeesSet", "original_total_additional_fees", "money"),
        _f("originalTotalDutiesSet", "original_total_duties", "money"),
        _f("originalTotalPriceSet", "original_total_price", "money"),
        _f("refundDiscrepancySet", "refund_discrepancy", "money"),
        _f("totalCapturableSet", "total_capturable", "money"),
        _f("totalOutstandingSet", "total_outstanding", "money"),
        _f("totalReceivedSet", "total_received", "money"),
        _f("totalRefundedSet", "total_refunded", "money"),
        _f("totalRefundedShippingSet", "total_refunded_shipping", "money"),
        _f("totalTipReceivedSet", "total_tip_received", "money"),
    ),
    "LineItem": (
        _f("id", "id", "id"),
        _f("product", "product_id", "ref"),
        _f("variant", "variant_id", "ref"),
        _f("title", "title", "text"),
        _f("variantTitle", "variant_title", "text"),
        _f("name", "name", "text"),
        _f("sku", "sku", "text"),
        _f("vendor", "vendor", "text"),
        _f("quantity", "quantity", "int"),
        _f("currentQuantity", "current_quantity", "int"),
        _f("refundableQuantity", "refundable_quantity", "int"),
        _f("unfulfilledQuantity", "unfulfilled_quantity", "int"),
        _f("nonFulfillableQuantity", "non_fulfillable_quantity", "int"),
        _f("requiresShipping", "requires_shipping", "bool"),
        _f("taxable", "taxable", "bool"),
        _f("isGiftCard", "is_gift_card", "bool"),
        _f("merchantEditable", "merchant_editable", "bool"),
        _f("restockable", "restockable", "bool"),
        _f("originalUnitPriceSet", "original_unit_price", "money"),
        _f("discountedUnitPriceSet", "discounted_unit_price", "money"),
        _f(
            "discountedUnitPriceAfterAllDiscountsSet",
            "discounted_unit_price_after_all_discounts",
            "money",
        ),
        _f("originalTotalSet", "original_total", "money"),
        _f("discountedTotalSet", "discounted_total", "money"),
        _f(
            "priceAfterAllDiscountsBeforeTaxesSet",
            "price_after_all_discounts_before_taxes",
            "money",
        ),
        _f("totalDiscountSet", "total_discount", "money"),
        _f("unfulfilledDiscountedTotalSet", "unfulfilled_discounted_total", "money"),
        _f("unfulfilledOriginalTotalSet", "unfulfilled_original_total", "money"),
    ),
    "FulfillmentOrderAssignedLocation": (
        _f("location", "location_id", "ref"),
        _f("name", "name", "text"),
        _f("address1", "address1", "text"),
        _f("address2", "address2", "text"),
        _f("city", "city", "text"),
        _f("province", "province", "text"),
        _f("zip", "zip", "text"),
        _f("countryCode", "country_code", "text"),
        _f("phone", "phone", "text"),
    ),
    "FulfillmentOrderLineItem": (
        _f("id", "id", "id"),
        _f("lineItem", "line_item_id", "ref"),
        _f("inventoryItemId", "inventory_item_id", "text"),
        _f("productTitle", "product_title", "text"),
        _f("variantTitle", "variant_title", "text"),
        _f("sku", "sku", "text"),
        _f("vendor", "vendor", "text"),
        _f("totalQuantity", "total_quantity", "int"),
        _f("remainingQuantity", "remaining_quantity", "int"),
        _f("requiresShipping", "requires_shipping", "bool"),
    ),
    "FulfillmentOrder": (
        _f("id", "id", "id"),
        _f("status", "status", "text"),
        _f("requestStatus", "request_status", "text"),
        _f("orderId", "order_id", "text"),
        _f("orderName", "order_name", "text"),
        _f("orderProcessedAt", "order_processed_at", "text"),
        _f("fulfillAt", "fulfill_at", "text"),
        _f("fulfillBy", "fulfill_by", "text"),
        _f("createdAt", "created_at", "text"),
        _f("updatedAt", "updated_at", "text"),
        _f("assignedLocation", "assigned_location", "record", "FulfillmentOrderAssignedLocation"),
        _f("lineItems", "line_items", "connection", "FulfillmentOrderLineItem"),
    ),
    "FulfillmentTrackingInfo": (
        _f("company", "company", "text"),
        _f("number", "number", "text"),
        _f("url", "url", "text"),
    ),
    "Fulfillment": (
        _f("id", "id", "id"),
        _f("name", "name", "text"),
        _f("status", "status", "text"),
        _f("displayStatus", "display_status", "text"),
        _f("legacyResourceId", "legacy_resource_id", "text"),
        _f("totalQuantity", "total_quantity", "int"),
        _f("requiresShipping", "requires_shipping", "bool"),
        _f("createdAt", "created_at", "text"),
        _f("updatedAt", "updated_at", "text"),
        _f("inTransitAt", "in_transit_at", "text"),
        _f("estimatedDeliveryAt", "estimated_delivery_at", "text"),
        _f("deliveredAt", "delivered_at", "text"),
        _f("trackingInfo", "tracking_info", "records", "FulfillmentTrackingInfo"),
    ),
    "InventoryChange": (
        _f("item", "inventory_item_id", "ref"),
        _f("location", "location_id", "ref"),
        _f("name", "name", "text"),
        _f("delta", "delta", "int"),
        _f("quantityAfterChange", "quantity_after_change", "int"),
        _f("ledgerDocumentUri", "ledger_document_uri", "text"),
    ),
    "InventoryAdjustmentGroup": (
        _f("id", "id", "text"),
        _f("createdAt", "created_at", "text"),
        _f("reason", "reason", "text"),
        _f("referenceDocumentUri", "reference_document_uri", "text"),
        _f("changes", "changes", "records", "InventoryChange"),
    ),
}

#: Records whose nested lists are never clipped: an adjustment receipt with
#: changes dropped would be a truncated receipt for a write that happened.
_UNCLIPPED: frozenset[str] = frozenset({"InventoryAdjustmentGroup"})

_SCALAR_SCHEMAS: dict[str, dict[str, Any]] = {
    "id": {"type": "string"},
    "text": {"type": ["string", "null"]},
    "int": {"type": ["integer", "null"]},
    "number": {"type": ["number", "null"]},
    "bool": {"type": ["boolean", "null"]},
    "json": {},
    "list_text": {"type": "array", "items": {"type": "string"}},
    "ref": {"type": ["string", "null"]},
}

MONEY_SCHEMA: dict[str, Any] = {
    "type": ["object", "null"],
    "additionalProperties": False,
    "required": ["amount", "currency_code"],
    "properties": {
        "amount": {"type": ["string", "null"]},
        "currency_code": {"type": ["string", "null"]},
    },
}


def keys(name: str) -> tuple[str, ...]:
    """The published keys of one record, in table order, each once."""
    seen: dict[str, None] = {}
    for field in RECORDS[name]:
        seen.setdefault(field.key, None)
        if field.kind == "connection":
            seen.setdefault(f"{field.key}_page_info", None)
    return tuple(seen)


def schema(name: str, *, nullable: bool = False) -> dict[str, Any]:
    """The JSON Schema one record is published under."""
    properties: dict[str, Any] = {}
    for field in RECORDS[name]:
        if field.key in properties:
            continue
        properties[field.key] = _field_schema(field)
        if field.kind == "connection":
            properties[f"{field.key}_page_info"] = schema("PageInfo")
    published_keys = list(properties)
    return {
        "type": ["object", "null"] if nullable else "object",
        "additionalProperties": False,
        "required": published_keys,
        "properties": properties,
    }


def _field_schema(field: Field) -> dict[str, Any]:
    if field.kind in _SCALAR_SCHEMAS:
        return dict(_SCALAR_SCHEMAS[field.kind])
    if field.kind == "money":
        return dict(MONEY_SCHEMA)
    if field.kind == "record":
        return schema(field.target, nullable=True)
    if field.kind in ("records", "connection"):
        return {"type": "array", "items": schema(field.target)}
    raise ValueError(f"unknown field kind {field.kind!r}")  # pragma: no cover - packaging


def shape(name: str, node: Any, **known: Any) -> dict[str, Any]:
    """Turn one Shopify node into the declared record.

    ``known`` supplies keys this side already knows better than the response —
    a metafield's owner, for instance, is the record that was asked about.
    """
    record = node if isinstance(node, Mapping) else {}
    typename = record.get("__typename")
    shaped: dict[str, Any] = {}
    for field in RECORDS[name]:
        if field.on and typename not in (field.on, None):
            shaped.setdefault(field.key, _empty(field))
            continue
        if field.on and typename is None and field.key in shaped:
            continue
        shaped[field.key] = _value(field, record.get(field.graphql), clip=name not in _UNCLIPPED)
        if field.kind == "connection":
            shaped[f"{field.key}_page_info"] = shape(
                "PageInfo", mapping(record.get(field.graphql)).get("pageInfo")
            )
    shaped.update(known)
    return shaped


def _empty(field: Field) -> Any:
    return [] if field.kind in ("list_text", "records", "connection") else None


def _value(field: Field, value: Any, *, clip: bool) -> Any:
    kind = field.kind
    if kind == "id":
        return value if isinstance(value, str) else ""
    if kind == "text":
        return value if isinstance(value, str) else None
    if kind == "int":
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    if kind == "number":
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if kind == "bool":
        return value if isinstance(value, bool) else None
    if kind == "json":
        return value
    if kind == "list_text":
        return [item for item in _list(value, clip=clip) if isinstance(item, str)]
    if kind == "ref":
        found = mapping(value).get("id")
        return found if isinstance(found, str) else None
    if kind == "money":
        shop_money = mapping(mapping(value).get("shopMoney"))
        if not shop_money:
            return None
        return shape(MONEY_V2, shop_money)
    if kind == "record":
        return shape(field.target, value) if isinstance(value, Mapping) else None
    if kind == "records":
        return [shape(field.target, item) for item in _list(value, clip=clip)]
    if kind == "connection":
        return [shape(field.target, item) for item in _list(mapping(value).get("nodes"), clip=clip)]
    raise ValueError(f"unknown field kind {kind!r}")  # pragma: no cover - packaging


def _list(value: Any, *, clip: bool) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    items = value[:MAX_NESTED_ITEMS] if clip else value
    return [item for item in items if isinstance(item, (Mapping, str))]


def mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def selection(name: str, indent: str = "") -> str:
    """The GraphQL selection one table declares, for writing documents by hand.

    Not used at runtime: documents stay literal. Tests compare each literal
    document against this, and maintainers paste it when a table changes.
    """
    lines: list[str] = []
    plain = [field for field in RECORDS[name] if not field.on]
    fragments: dict[str, list[Field]] = {}
    for field in RECORDS[name]:
        if field.on:
            fragments.setdefault(field.on, []).append(field)
    for field in plain:
        lines.append(indent + _selected(field, indent))
    for condition, fields in fragments.items():
        inner = " ".join(_selected(field, "") for field in fields)
        lines.append(f"{indent}... on {condition} {{ {inner} }}")
    return "\n".join(lines)


def _selected(field: Field, indent: str) -> str:
    if field.kind == "ref":
        return f"{field.graphql} {{ id }}"
    if field.kind == "money":
        return f"{field.graphql} {{ shopMoney {{ amount currencyCode }} }}"
    if field.kind in ("record", "records"):
        inner = " ".join(_selected(child, "") for child in RECORDS[field.target] if not child.on)
        return f"{field.graphql} {{ {inner} }}"
    if field.kind == "connection":
        inner = " ".join(_selected(child, "") for child in RECORDS[field.target])
        return f"{field.graphql} {{ pageInfo {{ hasNextPage endCursor }} nodes {{ {inner} }} }}"
    return field.graphql


__all__ = [
    "MAX_NESTED_ITEMS",
    "MONEY_SCHEMA",
    "RECORDS",
    "Field",
    "keys",
    "mapping",
    "schema",
    "selection",
    "shape",
]
