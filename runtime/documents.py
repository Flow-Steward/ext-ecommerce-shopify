"""The complete set of GraphQL documents this extension can send.

Seven fixed documents, one per Shopify-contacting operation. Nothing here is
built from caller input: every value a workflow supplies travels as a GraphQL
*variable*, never as document text. There is no string interpolation, no
document assembly, and no way to reach a query that is not written out below.

Each document was validated against Shopify Admin API ``2026-07`` with the
Shopify AI Toolkit (``scripts/validate.mjs --version 2026-07``); the evidence is
recorded in ``README.md``. ``API_VERSION`` is the only place the version is
written, and the transport builds the endpoint path from it.
"""

from __future__ import annotations

API_VERSION = "2026-07"

#: The two quantity states this extension reads and writes. ``available`` is the
#: one it sets; ``on_hand`` is returned alongside it as context.
AVAILABLE_QUANTITY_NAME = "available"
ON_HAND_QUANTITY_NAME = "on_hand"

#: Fixed values for every ``inventorySetQuantities`` request. A workflow cannot
#: choose the quantity name or the reason: this extension sets absolute
#: ``available`` quantities and records them as a correction.
SET_QUANTITIES_NAME = AVAILABLE_QUANTITY_NAME
SET_QUANTITIES_REASON = "correction"

#: The reference document URI template. The host's external effect id is what
#: makes one call distinguishable from a retry of the same call.
REFERENCE_DOCUMENT_URI_PREFIX = "gid://flow-steward/ExternalEffect/"

#: Every product this extension creates starts unpublished. Publishing is a
#: merchandising decision, and nothing here is allowed to make it by accident.
CREATE_PRODUCT_STATUS = "DRAFT"

#: Fixed arguments written into the mutation documents themselves rather than
#: passed as variables, so no caller value can reach them. Named here so tests
#: can assert the document text still carries them.
VARIANTS_BULK_CREATE_STRATEGY = "PRESERVE_STANDALONE_VARIANT"
VARIANTS_BULK_UPDATE_PARTIAL = "allowPartialUpdates: false"
FULFILLMENT_NOTIFY_CUSTOMER = "notifyCustomer: false"

#: Bounded page sizes for the sub-selections a caller does not paginate.
TRACKING_INFO_LIMIT = 25

TEST_CONNECTION = """\
query FlowStewardTestConnection {
  shop {
    id
    name
    myshopifyDomain
  }
  currentAppInstallation {
    accessScopes {
      handle
    }
  }
}
"""

GET_SHOP = """\
query FlowStewardGetShop {
  shop {
    id
    name
    myshopifyDomain
    currencyCode
    ianaTimezone
  }
}
"""

LIST_LOCATIONS = """\
query FlowStewardListLocations($first: Int!, $after: String, $includeInactive: Boolean!) {
  locations(first: $first, after: $after, includeInactive: $includeInactive) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      id
      name
      isActive
      fulfillsOnlineOrders
      shipsInventory
    }
  }
}
"""

LIST_INVENTORY_ITEMS = """\
query FlowStewardListInventoryItems($first: Int!, $after: String, $query: String) {
  inventoryItems(first: $first, after: $after, query: $query) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      id
      sku
      tracked
      requiresShipping
      updatedAt
    }
  }
}
"""

GET_INVENTORY_ITEM = """\
query FlowStewardGetInventoryItem($id: ID!) {
  inventoryItem(id: $id) {
    __typename
    id
    sku
    tracked
    requiresShipping
    updatedAt
  }
}
"""

GET_INVENTORY_LEVELS_BATCH = """\
query FlowStewardInventoryLevelsBatch($ids: [ID!]!, $locationId: ID!, \
$includeInactive: Boolean!) {
  nodes(ids: $ids) {
    __typename
    ... on InventoryItem {
      id
      sku
      tracked
      inventoryLevel(locationId: $locationId, includeInactive: $includeInactive) {
        id
        location {
          id
          isActive
        }
        quantities(names: ["available", "on_hand"]) {
          name
          quantity
        }
      }
    }
  }
}
"""

SET_INVENTORY_QUANTITIES = """\
mutation FlowStewardSetInventoryQuantities($input: InventorySetQuantitiesInput!, \
$idempotencyKey: String!) {
  inventorySetQuantities(input: $input) @idempotent(key: $idempotencyKey) {
    inventoryAdjustmentGroup {
      id
      createdAt
      reason
      referenceDocumentUri
      changes {
        name
        delta
        quantityAfterChange
        item {
          id
        }
        location {
          id
        }
      }
    }
    userErrors {
      code
      field
      message
    }
  }
}
"""

LIST_PRODUCTS = """\
query FlowStewardListProducts($first: Int!, $after: String, $query: String) {
  products(first: $first, after: $after, query: $query, sortKey: ID) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      title
      handle
      descriptionHtml
      vendor
      productType
      status
      tags
      createdAt
      updatedAt
      category { id }
      seo { title description }
      options { id name position }
    }
  }
}
"""

EXPORT_PRODUCTS = """\
query FlowStewardExportProducts($first: Int!, $after: String, $query: String) {
  products(first: $first, after: $after, query: $query, sortKey: ID) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      title
      handle
      descriptionHtml
      vendor
      productType
      status
      tags
      createdAt
      updatedAt
      category { id }
      seo { title description }
      options { id name position }
    }
  }
}
"""

GET_PRODUCT = """\
query FlowStewardGetProduct($id: ID!) {
  product(id: $id) {
    id
    title
    handle
    descriptionHtml
    vendor
    productType
    status
    tags
    createdAt
    updatedAt
    category { id }
    seo { title description }
    options { id name position }
  }
}
"""

LIST_PRODUCT_VARIANTS = """\
query FlowStewardListProductVariants($first: Int!, $after: String) {
  productVariants(first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      title
      barcode
      price
      compareAtPrice
      inventoryPolicy
      taxable
      createdAt
      updatedAt
      product { id }
      selectedOptions { name value }
      inventoryItem { id sku tracked requiresShipping }
    }
  }
}
"""

GET_PRODUCT_VARIANT = """\
query FlowStewardGetProductVariant($id: ID!) {
  productVariant(id: $id) {
    id
    title
    barcode
    price
    compareAtPrice
    inventoryPolicy
    taxable
    createdAt
    updatedAt
    product { id }
    selectedOptions { name value }
    inventoryItem { id sku tracked requiresShipping }
  }
}
"""

LIST_CATALOG_METAFIELDS = """\
query FlowStewardListCatalogMetafields($id: ID!, $first: Int!, $after: String) {
  node(id: $id) {
    __typename
    ... on Product {
      id
      metafields(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { id namespace key type value compareDigest createdAt updatedAt }
      }
    }
    ... on ProductVariant {
      id
      metafields(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { id namespace key type value compareDigest createdAt updatedAt }
      }
    }
  }
}
"""

LIST_PRODUCT_MEDIA = """\
query FlowStewardListProductMedia($id: ID!, $first: Int!, $after: String) {
  product(id: $id) {
    id
    media(first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        mediaContentType
        alt
        status
        preview { status image { width height } }
      }
    }
  }
}
"""

CREATE_PRODUCT = """\
mutation FlowStewardCreateProduct($product: ProductCreateInput!, $media: [CreateMediaInput!]) {
  productCreate(product: $product, media: $media) {
    product {
      id
      title
      handle
      descriptionHtml
      vendor
      productType
      status
      tags
      createdAt
      updatedAt
      category { id }
      seo { title description }
      options { id name position }
      variants(first: 1) {
        nodes {
          id
          title
          barcode
          price
          compareAtPrice
          inventoryPolicy
          taxable
          createdAt
          updatedAt
          product { id }
          selectedOptions { name value }
          inventoryItem { id sku tracked requiresShipping }
        }
      }
    }
    userErrors { field message }
  }
}
"""

UPDATE_PRODUCT = """\
mutation FlowStewardUpdateProduct($product: ProductUpdateInput!) {
  productUpdate(product: $product) {
    product {
      id
      title
      handle
      descriptionHtml
      vendor
      productType
      status
      tags
      createdAt
      updatedAt
      category { id }
      seo { title description }
      options { id name position }
    }
    userErrors { field message }
  }
}
"""

CREATE_PRODUCT_VARIANTS_BATCH = """\
mutation FlowStewardCreateProductVariants($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkCreate(
    productId: $productId
    variants: $variants
    strategy: PRESERVE_STANDALONE_VARIANT
  ) {
    productVariants {
      id
      title
      barcode
      price
      compareAtPrice
      inventoryPolicy
      taxable
      product { id }
      selectedOptions { name value }
      inventoryItem { id sku tracked requiresShipping }
    }
    userErrors { field message code }
  }
}
"""

UPDATE_PRODUCT_VARIANTS_BATCH = """\
mutation FlowStewardUpdateProductVariants($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(
    productId: $productId
    variants: $variants
    allowPartialUpdates: false
  ) {
    productVariants {
      id
      title
      barcode
      price
      compareAtPrice
      inventoryPolicy
      taxable
      product { id }
      selectedOptions { name value }
      inventoryItem { id sku tracked requiresShipping }
    }
    userErrors { field message code }
  }
}
"""

SET_CATALOG_METAFIELDS = """\
mutation FlowStewardSetCatalogMetafields($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields {
      id
      namespace
      key
      type
      value
      compareDigest
      createdAt
      updatedAt
      owner {
        __typename
        ... on Product { id }
        ... on ProductVariant { id }
      }
    }
    userErrors { field message code elementIndex }
  }
}
"""

UPDATE_PRODUCT_MEDIA_ALT = """\
mutation FlowStewardUpdateProductMediaAlt($files: [FileUpdateInput!]!) {
  fileUpdate(files: $files) {
    files {
      id
      alt
      fileStatus
      createdAt
      updatedAt
    }
    userErrors { field message code }
  }
}
"""

LIST_ORDERS = """\
query FlowStewardListOrders($first: Int!, $after: String) {
  orders(first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      createdAt
      updatedAt
      processedAt
      cancelledAt
      closedAt
      displayFinancialStatus
      displayFulfillmentStatus
      currencyCode
      tags
      note
      poNumber
      customAttributes { key value }
      totalPriceSet { shopMoney { amount currencyCode } }
      subtotalPriceSet { shopMoney { amount currencyCode } }
      totalTaxSet { shopMoney { amount currencyCode } }
      totalShippingPriceSet { shopMoney { amount currencyCode } }
      totalDiscountsSet { shopMoney { amount currencyCode } }
    }
  }
}
"""

GET_ORDER = """\
query FlowStewardGetOrder($id: ID!) {
  order(id: $id) {
    id
    name
    createdAt
    updatedAt
    processedAt
    cancelledAt
    closedAt
    displayFinancialStatus
    displayFulfillmentStatus
    currencyCode
    tags
    note
    poNumber
    customAttributes { key value }
    totalPriceSet { shopMoney { amount currencyCode } }
    subtotalPriceSet { shopMoney { amount currencyCode } }
    totalTaxSet { shopMoney { amount currencyCode } }
    totalShippingPriceSet { shopMoney { amount currencyCode } }
    totalDiscountsSet { shopMoney { amount currencyCode } }
  }
}
"""

LIST_ORDER_LINE_ITEMS = """\
query FlowStewardListOrderLineItems($id: ID!, $first: Int!, $after: String) {
  order(id: $id) {
    id
    lineItems(first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        title
        name
        sku
        quantity
        currentQuantity
        refundableQuantity
        unfulfilledQuantity
        requiresShipping
        product { id }
        variant { id }
        originalUnitPriceSet { shopMoney { amount currencyCode } }
        discountedUnitPriceSet { shopMoney { amount currencyCode } }
        originalTotalSet { shopMoney { amount currencyCode } }
        discountedTotalSet { shopMoney { amount currencyCode } }
      }
    }
  }
}
"""

LIST_ORDER_METAFIELDS = """\
query FlowStewardListOrderMetafields($id: ID!, $first: Int!, $after: String) {
  order(id: $id) {
    id
    metafields(first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { id namespace key type value compareDigest createdAt updatedAt }
    }
  }
}
"""

LIST_ORDER_FULFILLMENT_ORDERS = """\
query FlowStewardListOrderFulfillmentOrders($id: ID!, $first: Int!, $after: String, $lineItemsFirst: Int!) {
  order(id: $id) {
    id
    fulfillmentOrders(first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        status
        requestStatus
        createdAt
        updatedAt
        assignedLocation { name location { id } }
        lineItems(first: $lineItemsFirst) {
          pageInfo { hasNextPage endCursor }
          nodes { id totalQuantity remainingQuantity lineItem { id } }
        }
      }
    }
  }
}
"""

GET_FULFILLMENT_ORDER = """\
query FlowStewardGetFulfillmentOrder($id: ID!, $lineItemsFirst: Int!, $lineItemsAfter: String) {
  fulfillmentOrder(id: $id) {
    id
    status
    requestStatus
    createdAt
    updatedAt
    assignedLocation { name location { id } }
    lineItems(first: $lineItemsFirst, after: $lineItemsAfter) {
      pageInfo { hasNextPage endCursor }
      nodes { id totalQuantity remainingQuantity lineItem { id } }
    }
  }
}
"""

LIST_ORDER_FULFILLMENTS = """\
query FlowStewardListOrderFulfillments($id: ID!, $first: Int!, $trackingFirst: Int!) {
  order(id: $id) {
    id
    fulfillmentsCount { count precision }
    fulfillments(first: $first) {
      id
      status
      createdAt
      updatedAt
      trackingInfo(first: $trackingFirst) { company number url }
    }
  }
}
"""

UPDATE_ORDER_METADATA = """\
mutation FlowStewardUpdateOrderMetadata($input: OrderInput!) {
  orderUpdate(input: $input) {
    order {
      id
      name
      updatedAt
      tags
      note
      poNumber
      customAttributes { key value }
    }
    userErrors { field message }
  }
}
"""

SET_ORDER_METAFIELDS = """\
mutation FlowStewardSetOrderMetafields($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields {
      id
      namespace
      key
      type
      value
      compareDigest
      createdAt
      updatedAt
      owner {
        __typename
        ... on Order { id }
      }
    }
    userErrors { field message code elementIndex }
  }
}
"""

CREATE_FULFILLMENT = """\
mutation FlowStewardCreateFulfillment($fulfillment: FulfillmentInput!, $trackingFirst: Int!) {
  fulfillmentCreate(fulfillment: $fulfillment) {
    fulfillment {
      id
      status
      createdAt
      updatedAt
      trackingInfo(first: $trackingFirst) { company number url }
    }
    userErrors { field message }
  }
}
"""

UPDATE_FULFILLMENT_TRACKING = """\
mutation FlowStewardUpdateFulfillmentTracking($fulfillmentId: ID!, $trackingInfoInput: FulfillmentTrackingInput!, $trackingFirst: Int!) {
  fulfillmentTrackingInfoUpdate(
    fulfillmentId: $fulfillmentId
    trackingInfoInput: $trackingInfoInput
    notifyCustomer: false
  ) {
    fulfillment {
      id
      status
      createdAt
      updatedAt
      trackingInfo(first: $trackingFirst) { company number url }
    }
    userErrors { field message }
  }
}
"""

#: Every document, keyed by the operation that owns it. An operation without an
#: entry here never reaches the transport.
CREATE_PRODUCTS_BULK = """\
mutation FlowStewardCreateProductsBulk($mutation: String!, $path: String!, $clientIdentifier: String!) {
  bulkOperationRunMutation(mutation: $mutation, stagedUploadPath: $path, clientIdentifier: $clientIdentifier) {
    bulkOperation { id status type }
    userErrors { field message code }
  }
}
"""

DOCUMENTS: dict[str, str] = {
    "test_connection": TEST_CONNECTION,
    "get_shop": GET_SHOP,
    "list_locations": LIST_LOCATIONS,
    "list_inventory_items": LIST_INVENTORY_ITEMS,
    "get_inventory_item": GET_INVENTORY_ITEM,
    "get_inventory_levels_batch": GET_INVENTORY_LEVELS_BATCH,
    "set_inventory_quantities": SET_INVENTORY_QUANTITIES,
    "list_products": LIST_PRODUCTS,
    "export_products": EXPORT_PRODUCTS,
    "get_product": GET_PRODUCT,
    "list_product_variants": LIST_PRODUCT_VARIANTS,
    "get_product_variant": GET_PRODUCT_VARIANT,
    "list_catalog_metafields": LIST_CATALOG_METAFIELDS,
    "list_product_media": LIST_PRODUCT_MEDIA,
    "create_product": CREATE_PRODUCT,
    "create_products_bulk": CREATE_PRODUCTS_BULK,
    "update_product": UPDATE_PRODUCT,
    "create_product_variants_batch": CREATE_PRODUCT_VARIANTS_BATCH,
    "update_product_variants_batch": UPDATE_PRODUCT_VARIANTS_BATCH,
    "set_catalog_metafields": SET_CATALOG_METAFIELDS,
    "update_product_media_alt": UPDATE_PRODUCT_MEDIA_ALT,
    "list_orders": LIST_ORDERS,
    "get_order": GET_ORDER,
    "list_order_line_items": LIST_ORDER_LINE_ITEMS,
    "list_order_metafields": LIST_ORDER_METAFIELDS,
    "list_order_fulfillment_orders": LIST_ORDER_FULFILLMENT_ORDERS,
    "get_fulfillment_order": GET_FULFILLMENT_ORDER,
    "list_order_fulfillments": LIST_ORDER_FULFILLMENTS,
    "update_order_metadata": UPDATE_ORDER_METADATA,
    "set_order_metafields": SET_ORDER_METAFIELDS,
    "create_fulfillment": CREATE_FULFILLMENT,
    "update_fulfillment_tracking": UPDATE_FULFILLMENT_TRACKING,
}

#: Field names deprecated by the 2026 compare-and-swap redesign. They are named
#: here so a test can prove the mutation document does not carry them: sending
#: either one against ``2026-07`` is a schema error, not a silent no-op.
FORBIDDEN_CAS_FIELDS: tuple[str, ...] = ("compareQuantity", "ignoreCompareQuantity")

__all__ = [
    "API_VERSION",
    "AVAILABLE_QUANTITY_NAME",
    "CREATE_FULFILLMENT",
    "CREATE_PRODUCT",
    "CREATE_PRODUCT_STATUS",
    "CREATE_PRODUCT_VARIANTS_BATCH",
    "DOCUMENTS",
    "FULFILLMENT_NOTIFY_CUSTOMER",
    "GET_FULFILLMENT_ORDER",
    "GET_INVENTORY_ITEM",
    "GET_INVENTORY_LEVELS_BATCH",
    "GET_ORDER",
    "GET_PRODUCT",
    "GET_PRODUCT_VARIANT",
    "GET_SHOP",
    "LIST_CATALOG_METAFIELDS",
    "LIST_INVENTORY_ITEMS",
    "LIST_LOCATIONS",
    "LIST_ORDERS",
    "LIST_ORDER_FULFILLMENTS",
    "LIST_ORDER_FULFILLMENT_ORDERS",
    "LIST_ORDER_LINE_ITEMS",
    "LIST_ORDER_METAFIELDS",
    "LIST_PRODUCTS",
    "LIST_PRODUCT_MEDIA",
    "LIST_PRODUCT_VARIANTS",
    "ON_HAND_QUANTITY_NAME",
    "REFERENCE_DOCUMENT_URI_PREFIX",
    "SET_CATALOG_METAFIELDS",
    "SET_INVENTORY_QUANTITIES",
    "SET_ORDER_METAFIELDS",
    "SET_QUANTITIES_NAME",
    "SET_QUANTITIES_REASON",
    "TEST_CONNECTION",
    "TRACKING_INFO_LIMIT",
    "UPDATE_FULFILLMENT_TRACKING",
    "UPDATE_ORDER_METADATA",
    "UPDATE_PRODUCT",
    "UPDATE_PRODUCT_MEDIA_ALT",
    "UPDATE_PRODUCT_VARIANTS_BATCH",
    "VARIANTS_BULK_CREATE_STRATEGY",
    "VARIANTS_BULK_UPDATE_PARTIAL",
]
