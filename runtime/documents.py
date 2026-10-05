"""The complete set of GraphQL documents this extension can send.

One fixed document per Shopify-contacting operation. Nothing here is
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

#: The quantity states this extension reads. ``available`` and ``on_hand`` are
#: the two ``inventorySetQuantities`` and ``productSet`` may write.
AVAILABLE_QUANTITY_NAME = "available"
ON_HAND_QUANTITY_NAME = "on_hand"
READ_QUANTITY_NAMES: tuple[str, ...] = (
    "available",
    "on_hand",
    "committed",
    "incoming",
    "reserved",
    "damaged",
    "safety_stock",
    "quality_control",
)

#: Defaults a caller may override. Each is the cautious choice: stock is set as
#: an ``available`` correction, a new product starts unpublished, a variant
#: batch keeps the standalone variant and applies all-or-nothing, and no
#: customer is emailed.
SET_QUANTITIES_NAME = AVAILABLE_QUANTITY_NAME
SET_QUANTITIES_REASON = "correction"
CREATE_PRODUCT_STATUS = "DRAFT"
VARIANTS_BULK_CREATE_STRATEGY = "PRESERVE_STANDALONE_VARIANT"
VARIANTS_BULK_ALLOW_PARTIAL_UPDATES = False
NOTIFY_CUSTOMER = False

#: The reference document URI template. The host's external effect id is what
#: makes one call distinguishable from a retry of the same call.
REFERENCE_DOCUMENT_URI_PREFIX = "gid://flow-steward/ExternalEffect/"

#: Bounded page sizes for the sub-selections a caller does not paginate.
TRACKING_INFO_LIMIT = 10

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
    checkoutApiSupported
    contactEmail
    createdAt
    customerAccounts
    description
    enabledPresentmentCurrencies
    marketingSmsConsentEnabledAtCheckout
    orderNumberFormatPrefix
    orderNumberFormatSuffix
    richTextEditorUrl
    setupRequired
    shipsToCountries
    taxShipping
    taxesIncluded
    timezoneAbbreviation
    timezoneOffset
    timezoneOffsetMinutes
    transactionalSmsDisabled
    unitSystem
    updatedAt
    url
    weightUnit
  }
}
"""

LIST_LOCATIONS = """\
query FlowStewardListLocations($first: Int!, $after: String, $includeInactive: Boolean!, \
$includeLegacy: Boolean!, $query: String, $sortKey: LocationSortKeys!, $reverse: Boolean!) {
  locations(
    first: $first
    after: $after
    includeInactive: $includeInactive
    includeLegacy: $includeLegacy
    query: $query
    sortKey: $sortKey
    reverse: $reverse
  ) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      isActive
      fulfillsOnlineOrders
      shipsInventory
      activatable
      addressVerified
      createdAt
      deactivatable
      deactivatedAt
      deletable
      hasActiveInventory
      hasUnfulfilledOrders
      isFulfillmentService
      legacyResourceId
      updatedAt
    }
  }
}
"""

LIST_INVENTORY_ITEMS = """\
query FlowStewardListInventoryItems($first: Int!, $after: String, $query: String, \
$reverse: Boolean!) {
  inventoryItems(first: $first, after: $after, query: $query, reverse: $reverse) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      sku
      tracked
      requiresShipping
      updatedAt
      countryCodeOfOrigin
      createdAt
      duplicateSkuCount
      harmonizedSystemCode
      inventoryHistoryUrl
      legacyResourceId
      provinceCodeOfOrigin
      unitCost { amount currencyCode }
      measurement { id weight { unit value } }
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
    countryCodeOfOrigin
    createdAt
    duplicateSkuCount
    harmonizedSystemCode
    inventoryHistoryUrl
    legacyResourceId
    provinceCodeOfOrigin
    unitCost { amount currencyCode }
    measurement { id weight { unit value } }
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
        isActive
        canDeactivate
        deactivationAlert
        createdAt
        updatedAt
        location { id isActive }
        quantities(names: ["available", "on_hand", "committed", "incoming", "reserved", "damaged", "safety_stock", "quality_control"]) { name quantity }
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
      changes { item { id } location { id } name delta quantityAfterChange ledgerDocumentUri }
    }
    userErrors { code field message }
  }
}
"""

LIST_PRODUCTS = """\
query FlowStewardListProducts($first: Int!, $after: String, $query: String, \
$sortKey: ProductSortKeys!, $reverse: Boolean!, $savedSearchId: ID) {
  products(
    first: $first
    after: $after
    query: $query
    sortKey: $sortKey
    reverse: $reverse
    savedSearchId: $savedSearchId
  ) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      title
      handle
      descriptionHtml
      description
      vendor
      productType
      status
      tags
      category { id }
      seo { title description }
      createdAt
      updatedAt
      publishedAt
      options { id name position values }
      combinedListingRole
      giftCardTemplateSuffix
      hasOnlyDefaultVariant
      hasOutOfStockVariants
      hasVariantsThatRequiresComponents
      isGiftCard
      legacyResourceId
      onlineStorePreviewUrl
      onlineStoreUrl
      requiresSellingPlan
      templateSuffix
      totalInventory
      tracksInventory
    }
  }
}
"""

EXPORT_PRODUCTS = """\
query FlowStewardExportProducts($first: Int!, $after: String, $query: String, \
$sortKey: ProductSortKeys!, $reverse: Boolean!, $savedSearchId: ID) {
  products(
    first: $first
    after: $after
    query: $query
    sortKey: $sortKey
    reverse: $reverse
    savedSearchId: $savedSearchId
  ) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      title
      handle
      descriptionHtml
      description
      vendor
      productType
      status
      tags
      category { id }
      seo { title description }
      createdAt
      updatedAt
      publishedAt
      options { id name position values }
      combinedListingRole
      giftCardTemplateSuffix
      hasOnlyDefaultVariant
      hasOutOfStockVariants
      hasVariantsThatRequiresComponents
      isGiftCard
      legacyResourceId
      onlineStorePreviewUrl
      onlineStoreUrl
      requiresSellingPlan
      templateSuffix
      totalInventory
      tracksInventory
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
    description
    vendor
    productType
    status
    tags
    category { id }
    seo { title description }
    createdAt
    updatedAt
    publishedAt
    options { id name position values }
    combinedListingRole
    giftCardTemplateSuffix
    hasOnlyDefaultVariant
    hasOutOfStockVariants
    hasVariantsThatRequiresComponents
    isGiftCard
    legacyResourceId
    onlineStorePreviewUrl
    onlineStoreUrl
    requiresSellingPlan
    templateSuffix
    totalInventory
    tracksInventory
  }
}
"""

LIST_PRODUCT_VARIANTS = """\
query FlowStewardListProductVariants($first: Int!, $after: String, $query: String, \
$sortKey: ProductVariantSortKeys!, $reverse: Boolean!, $savedSearchId: ID) {
  productVariants(
    first: $first
    after: $after
    query: $query
    sortKey: $sortKey
    reverse: $reverse
    savedSearchId: $savedSearchId
  ) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      product { id }
      title
      displayName
      sku
      barcode
      position
      price
      compareAtPrice
      unitPrice { amount currencyCode }
      showUnitPrice
      unitPriceMeasurement { measuredType quantityUnit quantityValue referenceUnit referenceValue }
      inventoryPolicy
      inventoryQuantity
      sellableOnlineQuantity
      availableForSale
      taxable
      requiresComponents
      legacyResourceId
      createdAt
      updatedAt
      selectedOptions { name value }
      inventoryItem { id sku tracked requiresShipping updatedAt countryCodeOfOrigin createdAt duplicateSkuCount harmonizedSystemCode inventoryHistoryUrl legacyResourceId provinceCodeOfOrigin unitCost { amount currencyCode } measurement { id weight { unit value } } }
    }
  }
}
"""

GET_PRODUCT_VARIANT = """\
query FlowStewardGetProductVariant($id: ID!) {
  productVariant(id: $id) {
    id
    product { id }
    title
    displayName
    sku
    barcode
    position
    price
    compareAtPrice
    unitPrice { amount currencyCode }
    showUnitPrice
    unitPriceMeasurement { measuredType quantityUnit quantityValue referenceUnit referenceValue }
    inventoryPolicy
    inventoryQuantity
    sellableOnlineQuantity
    availableForSale
    taxable
    requiresComponents
    legacyResourceId
    createdAt
    updatedAt
    selectedOptions { name value }
    inventoryItem { id sku tracked requiresShipping updatedAt countryCodeOfOrigin createdAt duplicateSkuCount harmonizedSystemCode inventoryHistoryUrl legacyResourceId provinceCodeOfOrigin unitCost { amount currencyCode } measurement { id weight { unit value } } }
  }
}
"""

LIST_CATALOG_METAFIELDS = """\
query FlowStewardListCatalogMetafields($id: ID!, $first: Int!, $after: String, \
$namespace: String, $keys: [String!], $reverse: Boolean!) {
  node(id: $id) {
    __typename
    ... on Product {
      id
      metafields(first: $first, after: $after, namespace: $namespace, keys: $keys, reverse: $reverse) {
        pageInfo { hasNextPage endCursor }
        nodes { id namespace key type value jsonValue compareDigest ownerType sizeInBytes legacyResourceId createdAt updatedAt }
      }
    }
    ... on ProductVariant {
      id
      metafields(first: $first, after: $after, namespace: $namespace, keys: $keys, reverse: $reverse) {
        pageInfo { hasNextPage endCursor }
        nodes { id namespace key type value jsonValue compareDigest ownerType sizeInBytes legacyResourceId createdAt updatedAt }
      }
    }
  }
}
"""

LIST_PRODUCT_MEDIA = """\
query FlowStewardListProductMedia($id: ID!, $first: Int!, $after: String, $query: String, \
$sortKey: ProductMediaSortKeys!, $reverse: Boolean!) {
  product(id: $id) {
    id
    media(first: $first, after: $after, query: $query, sortKey: $sortKey, reverse: $reverse) {
      pageInfo { hasNextPage endCursor }
      nodes {
        __typename
        id
        mediaContentType
        alt
        status
        preview { status image { id url altText width height thumbhash } }
        mediaErrors { code details message }
        mediaWarnings { code message }
        ... on MediaImage { createdAt updatedAt fileStatus mimeType image { id url altText width height thumbhash } }
        ... on Video { createdAt updatedAt fileStatus filename duration }
        ... on Model3d { createdAt updatedAt fileStatus filename }
        ... on ExternalVideo { createdAt updatedAt fileStatus embedUrl host originUrl }
      }
    }
  }
}
"""

CREATE_PRODUCT = """\
mutation FlowStewardCreateProduct($input: ProductSetInput!, $variantsFirst: Int!) {
  productSet(input: $input, synchronous: true) {
    product {
      id
      title
      handle
      descriptionHtml
      description
      vendor
      productType
      status
      tags
      category { id }
      seo { title description }
      createdAt
      updatedAt
      publishedAt
      options { id name position values }
      combinedListingRole
      giftCardTemplateSuffix
      hasOnlyDefaultVariant
      hasOutOfStockVariants
      hasVariantsThatRequiresComponents
      isGiftCard
      legacyResourceId
      onlineStorePreviewUrl
      onlineStoreUrl
      requiresSellingPlan
      templateSuffix
      totalInventory
      tracksInventory
      variants(first: $variantsFirst) {
        nodes {
          id
          product { id }
          title
          displayName
          sku
          barcode
          position
          price
          compareAtPrice
          unitPrice { amount currencyCode }
          showUnitPrice
          unitPriceMeasurement { measuredType quantityUnit quantityValue referenceUnit referenceValue }
          inventoryPolicy
          inventoryQuantity
          sellableOnlineQuantity
          availableForSale
          taxable
          requiresComponents
          legacyResourceId
          createdAt
          updatedAt
          selectedOptions { name value }
          inventoryItem { id sku tracked requiresShipping updatedAt countryCodeOfOrigin createdAt duplicateSkuCount harmonizedSystemCode inventoryHistoryUrl legacyResourceId provinceCodeOfOrigin unitCost { amount currencyCode } measurement { id weight { unit value } } }
        }
      }
    }
    userErrors { code field message }
  }
}
"""

UPDATE_PRODUCT = """\
mutation FlowStewardUpdateProduct($product: ProductUpdateInput!, $media: [CreateMediaInput!], \
$identifier: ProductUpdateIdentifiers) {
  productUpdate(product: $product, media: $media, identifier: $identifier) {
    product {
      id
      title
      handle
      descriptionHtml
      description
      vendor
      productType
      status
      tags
      category { id }
      seo { title description }
      createdAt
      updatedAt
      publishedAt
      options { id name position values }
      combinedListingRole
      giftCardTemplateSuffix
      hasOnlyDefaultVariant
      hasOutOfStockVariants
      hasVariantsThatRequiresComponents
      isGiftCard
      legacyResourceId
      onlineStorePreviewUrl
      onlineStoreUrl
      requiresSellingPlan
      templateSuffix
      totalInventory
      tracksInventory
    }
    userErrors { field message }
  }
}
"""

CREATE_PRODUCT_VARIANTS_BATCH = """\
mutation FlowStewardCreateProductVariants($productId: ID!, $variants: [ProductVariantsBulkInput!]!, \
$media: [CreateMediaInput!], $strategy: ProductVariantsBulkCreateStrategy!) {
  productVariantsBulkCreate(productId: $productId, variants: $variants, media: $media, strategy: $strategy) {
    productVariants {
      id
      product { id }
      title
      displayName
      sku
      barcode
      position
      price
      compareAtPrice
      unitPrice { amount currencyCode }
      showUnitPrice
      unitPriceMeasurement { measuredType quantityUnit quantityValue referenceUnit referenceValue }
      inventoryPolicy
      inventoryQuantity
      sellableOnlineQuantity
      availableForSale
      taxable
      requiresComponents
      legacyResourceId
      createdAt
      updatedAt
      selectedOptions { name value }
      inventoryItem { id sku tracked requiresShipping updatedAt countryCodeOfOrigin createdAt duplicateSkuCount harmonizedSystemCode inventoryHistoryUrl legacyResourceId provinceCodeOfOrigin unitCost { amount currencyCode } measurement { id weight { unit value } } }
    }
    userErrors { code field message }
  }
}
"""

UPDATE_PRODUCT_VARIANTS_BATCH = """\
mutation FlowStewardUpdateProductVariants($productId: ID!, $variants: [ProductVariantsBulkInput!]!, \
$media: [CreateMediaInput!], $allowPartialUpdates: Boolean!) {
  productVariantsBulkUpdate(
    productId: $productId
    variants: $variants
    media: $media
    allowPartialUpdates: $allowPartialUpdates
  ) {
    productVariants {
      id
      product { id }
      title
      displayName
      sku
      barcode
      position
      price
      compareAtPrice
      unitPrice { amount currencyCode }
      showUnitPrice
      unitPriceMeasurement { measuredType quantityUnit quantityValue referenceUnit referenceValue }
      inventoryPolicy
      inventoryQuantity
      sellableOnlineQuantity
      availableForSale
      taxable
      requiresComponents
      legacyResourceId
      createdAt
      updatedAt
      selectedOptions { name value }
      inventoryItem { id sku tracked requiresShipping updatedAt countryCodeOfOrigin createdAt duplicateSkuCount harmonizedSystemCode inventoryHistoryUrl legacyResourceId provinceCodeOfOrigin unitCost { amount currencyCode } measurement { id weight { unit value } } }
    }
    userErrors { code field message }
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
      jsonValue
      compareDigest
      ownerType
      sizeInBytes
      legacyResourceId
      createdAt
      updatedAt
      owner { __typename ... on Product { id } ... on ProductVariant { id } }
    }
    userErrors { code elementIndex field message }
  }
}
"""

UPDATE_PRODUCT_MEDIA = """\
mutation FlowStewardUpdateProductMedia($files: [FileUpdateInput!]!) {
  fileUpdate(files: $files) {
    files {
      __typename
      id
      alt
      fileStatus
      createdAt
      updatedAt
      preview { status image { id url altText width height thumbhash } }
      fileErrors { code details message }
      ... on MediaImage { mediaContentType status mimeType image { id url altText width height thumbhash } }
      ... on Video { mediaContentType status filename duration }
      ... on Model3d { mediaContentType status filename }
      ... on ExternalVideo { mediaContentType status embedUrl host originUrl }
      ... on GenericFile { mimeType url originalFileSize }
    }
    userErrors { code field message }
  }
}
"""

LIST_ORDERS = """\
query FlowStewardListOrders($first: Int!, $after: String, $query: String, \
$sortKey: OrderSortKeys!, $reverse: Boolean!, $savedSearchId: ID) {
  orders(
    first: $first
    after: $after
    query: $query
    sortKey: $sortKey
    reverse: $reverse
    savedSearchId: $savedSearchId
  ) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      number
      confirmationNumber
      legacyResourceId
      createdAt
      updatedAt
      processedAt
      cancelledAt
      cancelReason
      closedAt
      closed
      confirmed
      test
      edited
      displayFinancialStatus
      displayFulfillmentStatus
      returnStatus
      currencyCode
      presentmentCurrencyCode
      tags
      note
      poNumber
      customAttributes { key value }
      sourceName
      sourceIdentifier
      registeredSourceUrl
      statusPageUrl
      cartToken
      checkoutToken
      customerLocale
      customerAcceptsMarketing
      discountCode
      discountCodes
      paymentGatewayNames
      billingAddressMatchesShippingAddress
      canMarkAsPaid
      canNotifyCustomer
      capturable
      fulfillable
      fullyPaid
      unpaid
      refundable
      restockable
      requiresShipping
      merchantEditable
      merchantEditableErrors
      hasTimelineComment
      productNetwork
      dutiesIncluded
      estimatedTaxes
      taxExempt
      taxesIncluded
      subtotalLineItemsQuantity
      currentSubtotalLineItemsQuantity
      totalWeight
      currentTotalWeight
      totalPriceSet { shopMoney { amount currencyCode } }
      subtotalPriceSet { shopMoney { amount currencyCode } }
      totalTaxSet { shopMoney { amount currencyCode } }
      totalShippingPriceSet { shopMoney { amount currencyCode } }
      totalDiscountsSet { shopMoney { amount currencyCode } }
      cartDiscountAmountSet { shopMoney { amount currencyCode } }
      currentCartDiscountAmountSet { shopMoney { amount currencyCode } }
      currentShippingPriceSet { shopMoney { amount currencyCode } }
      currentSubtotalPriceSet { shopMoney { amount currencyCode } }
      currentTotalAdditionalFeesSet { shopMoney { amount currencyCode } }
      currentTotalDiscountsSet { shopMoney { amount currencyCode } }
      currentTotalDutiesSet { shopMoney { amount currencyCode } }
      currentTotalPriceSet { shopMoney { amount currencyCode } }
      currentTotalTaxSet { shopMoney { amount currencyCode } }
      netPaymentSet { shopMoney { amount currencyCode } }
      originalTotalAdditionalFeesSet { shopMoney { amount currencyCode } }
      originalTotalDutiesSet { shopMoney { amount currencyCode } }
      originalTotalPriceSet { shopMoney { amount currencyCode } }
      refundDiscrepancySet { shopMoney { amount currencyCode } }
      totalCapturableSet { shopMoney { amount currencyCode } }
      totalOutstandingSet { shopMoney { amount currencyCode } }
      totalReceivedSet { shopMoney { amount currencyCode } }
      totalRefundedSet { shopMoney { amount currencyCode } }
      totalRefundedShippingSet { shopMoney { amount currencyCode } }
      totalTipReceivedSet { shopMoney { amount currencyCode } }
    }
  }
}
"""

GET_ORDER = """\
query FlowStewardGetOrder($id: ID!) {
  order(id: $id) {
    id
    name
    number
    confirmationNumber
    legacyResourceId
    createdAt
    updatedAt
    processedAt
    cancelledAt
    cancelReason
    closedAt
    closed
    confirmed
    test
    edited
    displayFinancialStatus
    displayFulfillmentStatus
    returnStatus
    currencyCode
    presentmentCurrencyCode
    tags
    note
    poNumber
    customAttributes { key value }
    sourceName
    sourceIdentifier
    registeredSourceUrl
    statusPageUrl
    cartToken
    checkoutToken
    customerLocale
    customerAcceptsMarketing
    discountCode
    discountCodes
    paymentGatewayNames
    billingAddressMatchesShippingAddress
    canMarkAsPaid
    canNotifyCustomer
    capturable
    fulfillable
    fullyPaid
    unpaid
    refundable
    restockable
    requiresShipping
    merchantEditable
    merchantEditableErrors
    hasTimelineComment
    productNetwork
    dutiesIncluded
    estimatedTaxes
    taxExempt
    taxesIncluded
    subtotalLineItemsQuantity
    currentSubtotalLineItemsQuantity
    totalWeight
    currentTotalWeight
    totalPriceSet { shopMoney { amount currencyCode } }
    subtotalPriceSet { shopMoney { amount currencyCode } }
    totalTaxSet { shopMoney { amount currencyCode } }
    totalShippingPriceSet { shopMoney { amount currencyCode } }
    totalDiscountsSet { shopMoney { amount currencyCode } }
    cartDiscountAmountSet { shopMoney { amount currencyCode } }
    currentCartDiscountAmountSet { shopMoney { amount currencyCode } }
    currentShippingPriceSet { shopMoney { amount currencyCode } }
    currentSubtotalPriceSet { shopMoney { amount currencyCode } }
    currentTotalAdditionalFeesSet { shopMoney { amount currencyCode } }
    currentTotalDiscountsSet { shopMoney { amount currencyCode } }
    currentTotalDutiesSet { shopMoney { amount currencyCode } }
    currentTotalPriceSet { shopMoney { amount currencyCode } }
    currentTotalTaxSet { shopMoney { amount currencyCode } }
    netPaymentSet { shopMoney { amount currencyCode } }
    originalTotalAdditionalFeesSet { shopMoney { amount currencyCode } }
    originalTotalDutiesSet { shopMoney { amount currencyCode } }
    originalTotalPriceSet { shopMoney { amount currencyCode } }
    refundDiscrepancySet { shopMoney { amount currencyCode } }
    totalCapturableSet { shopMoney { amount currencyCode } }
    totalOutstandingSet { shopMoney { amount currencyCode } }
    totalReceivedSet { shopMoney { amount currencyCode } }
    totalRefundedSet { shopMoney { amount currencyCode } }
    totalRefundedShippingSet { shopMoney { amount currencyCode } }
    totalTipReceivedSet { shopMoney { amount currencyCode } }
  }
}
"""

LIST_ORDER_LINE_ITEMS = """\
query FlowStewardListOrderLineItems($id: ID!, $first: Int!, $after: String, $reverse: Boolean!) {
  order(id: $id) {
    id
    lineItems(first: $first, after: $after, reverse: $reverse) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        product { id }
        variant { id }
        title
        variantTitle
        name
        sku
        vendor
        quantity
        currentQuantity
        refundableQuantity
        unfulfilledQuantity
        nonFulfillableQuantity
        requiresShipping
        taxable
        isGiftCard
        merchantEditable
        restockable
        originalUnitPriceSet { shopMoney { amount currencyCode } }
        discountedUnitPriceSet { shopMoney { amount currencyCode } }
        discountedUnitPriceAfterAllDiscountsSet { shopMoney { amount currencyCode } }
        originalTotalSet { shopMoney { amount currencyCode } }
        discountedTotalSet { shopMoney { amount currencyCode } }
        priceAfterAllDiscountsBeforeTaxesSet { shopMoney { amount currencyCode } }
        totalDiscountSet { shopMoney { amount currencyCode } }
        unfulfilledDiscountedTotalSet { shopMoney { amount currencyCode } }
        unfulfilledOriginalTotalSet { shopMoney { amount currencyCode } }
      }
    }
  }
}
"""

LIST_ORDER_METAFIELDS = """\
query FlowStewardListOrderMetafields($id: ID!, $first: Int!, $after: String, \
$namespace: String, $keys: [String!], $reverse: Boolean!) {
  order(id: $id) {
    id
    metafields(first: $first, after: $after, namespace: $namespace, keys: $keys, reverse: $reverse) {
      pageInfo { hasNextPage endCursor }
      nodes { id namespace key type value jsonValue compareDigest ownerType sizeInBytes legacyResourceId createdAt updatedAt }
      }
  }
}
"""

LIST_ORDER_FULFILLMENT_ORDERS = """\
query FlowStewardListOrderFulfillmentOrders($id: ID!, $first: Int!, $after: String, \
$reverse: Boolean!, $displayable: Boolean!, $query: String, $lineItemsFirst: Int!) {
  order(id: $id) {
    id
    fulfillmentOrders(
      first: $first
      after: $after
      reverse: $reverse
      displayable: $displayable
      query: $query
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        status
        requestStatus
        orderId
        orderName
        orderProcessedAt
        fulfillAt
        fulfillBy
        createdAt
        updatedAt
        assignedLocation { location { id } name address1 address2 city province zip countryCode phone }
        lineItems(first: $lineItemsFirst) { pageInfo { hasNextPage endCursor } nodes { id lineItem { id } inventoryItemId productTitle variantTitle sku vendor totalQuantity remainingQuantity requiresShipping } }
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
    orderId
    orderName
    orderProcessedAt
    fulfillAt
    fulfillBy
    createdAt
    updatedAt
    assignedLocation { location { id } name address1 address2 city province zip countryCode phone }
    lineItems(first: $lineItemsFirst, after: $lineItemsAfter) { pageInfo { hasNextPage endCursor } nodes { id lineItem { id } inventoryItemId productTitle variantTitle sku vendor totalQuantity remainingQuantity requiresShipping } }
  }
}
"""

LIST_ORDER_FULFILLMENTS = """\
query FlowStewardListOrderFulfillments($id: ID!, $first: Int!, $query: String, \
$trackingFirst: Int!) {
  order(id: $id) {
    id
    fulfillmentsCount { count precision }
    fulfillments(first: $first, query: $query) {
      id
      name
      status
      displayStatus
      legacyResourceId
      totalQuantity
      requiresShipping
      createdAt
      updatedAt
      inTransitAt
      estimatedDeliveryAt
      deliveredAt
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
      number
      confirmationNumber
      legacyResourceId
      createdAt
      updatedAt
      processedAt
      cancelledAt
      cancelReason
      closedAt
      closed
      confirmed
      test
      edited
      displayFinancialStatus
      displayFulfillmentStatus
      returnStatus
      currencyCode
      presentmentCurrencyCode
      tags
      note
      poNumber
      customAttributes { key value }
      sourceName
      sourceIdentifier
      registeredSourceUrl
      statusPageUrl
      cartToken
      checkoutToken
      customerLocale
      customerAcceptsMarketing
      discountCode
      discountCodes
      paymentGatewayNames
      billingAddressMatchesShippingAddress
      canMarkAsPaid
      canNotifyCustomer
      capturable
      fulfillable
      fullyPaid
      unpaid
      refundable
      restockable
      requiresShipping
      merchantEditable
      merchantEditableErrors
      hasTimelineComment
      productNetwork
      dutiesIncluded
      estimatedTaxes
      taxExempt
      taxesIncluded
      subtotalLineItemsQuantity
      currentSubtotalLineItemsQuantity
      totalWeight
      currentTotalWeight
      totalPriceSet { shopMoney { amount currencyCode } }
      subtotalPriceSet { shopMoney { amount currencyCode } }
      totalTaxSet { shopMoney { amount currencyCode } }
      totalShippingPriceSet { shopMoney { amount currencyCode } }
      totalDiscountsSet { shopMoney { amount currencyCode } }
      cartDiscountAmountSet { shopMoney { amount currencyCode } }
      currentCartDiscountAmountSet { shopMoney { amount currencyCode } }
      currentShippingPriceSet { shopMoney { amount currencyCode } }
      currentSubtotalPriceSet { shopMoney { amount currencyCode } }
      currentTotalAdditionalFeesSet { shopMoney { amount currencyCode } }
      currentTotalDiscountsSet { shopMoney { amount currencyCode } }
      currentTotalDutiesSet { shopMoney { amount currencyCode } }
      currentTotalPriceSet { shopMoney { amount currencyCode } }
      currentTotalTaxSet { shopMoney { amount currencyCode } }
      netPaymentSet { shopMoney { amount currencyCode } }
      originalTotalAdditionalFeesSet { shopMoney { amount currencyCode } }
      originalTotalDutiesSet { shopMoney { amount currencyCode } }
      originalTotalPriceSet { shopMoney { amount currencyCode } }
      refundDiscrepancySet { shopMoney { amount currencyCode } }
      totalCapturableSet { shopMoney { amount currencyCode } }
      totalOutstandingSet { shopMoney { amount currencyCode } }
      totalReceivedSet { shopMoney { amount currencyCode } }
      totalRefundedSet { shopMoney { amount currencyCode } }
      totalRefundedShippingSet { shopMoney { amount currencyCode } }
      totalTipReceivedSet { shopMoney { amount currencyCode } }
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
      jsonValue
      compareDigest
      ownerType
      sizeInBytes
      legacyResourceId
      createdAt
      updatedAt
      owner { __typename ... on Order { id } }
    }
    userErrors { code elementIndex field message }
  }
}
"""

CREATE_FULFILLMENT = """\
mutation FlowStewardCreateFulfillment($fulfillment: FulfillmentInput!, $message: String, \
$trackingFirst: Int!) {
  fulfillmentCreate(fulfillment: $fulfillment, message: $message) {
    fulfillment {
      id
      name
      status
      displayStatus
      legacyResourceId
      totalQuantity
      requiresShipping
      createdAt
      updatedAt
      inTransitAt
      estimatedDeliveryAt
      deliveredAt
      trackingInfo(first: $trackingFirst) { company number url }
    }
    userErrors { field message }
  }
}
"""

UPDATE_FULFILLMENT_TRACKING = """\
mutation FlowStewardUpdateFulfillmentTracking($fulfillmentId: ID!, \
$trackingInfoInput: FulfillmentTrackingInput!, $notifyCustomer: Boolean!, $trackingFirst: Int!) {
  fulfillmentTrackingInfoUpdate(
    fulfillmentId: $fulfillmentId
    trackingInfoInput: $trackingInfoInput
    notifyCustomer: $notifyCustomer
  ) {
    fulfillment {
      id
      name
      status
      displayStatus
      legacyResourceId
      totalQuantity
      requiresShipping
      createdAt
      updatedAt
      inTransitAt
      estimatedDeliveryAt
      deliveredAt
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
    "update_product_media": UPDATE_PRODUCT_MEDIA,
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
    "NOTIFY_CUSTOMER",
    "ON_HAND_QUANTITY_NAME",
    "READ_QUANTITY_NAMES",
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
    "UPDATE_PRODUCT_MEDIA",
    "UPDATE_PRODUCT_VARIANTS_BATCH",
    "VARIANTS_BULK_ALLOW_PARTIAL_UPDATES",
    "VARIANTS_BULK_CREATE_STRATEGY",
]
