"""Fixed, bounded documents for optional catalog export relations."""

IMAGES = """\
query FlowStewardExportImages($ids: [ID!]!, $after: String) {
  nodes(ids: $ids) {
    id
    ... on Product {
      media(first: 50, after: $after, query: "media_type:IMAGE", sortKey: POSITION) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          alt
          status
          ... on MediaImage { image { url width height } }
        }
      }
    }
  }
}
"""

VARIANTS = """\
query FlowStewardExportVariants($ids: [ID!]!, $after: String) {
  nodes(ids: $ids) {
    id
    ... on Product {
      variants(first: 20, after: $after) {
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
  }
}
"""

INVENTORY = """\
query FlowStewardExportInventory($ids: [ID!]!, $after: String) {
  nodes(ids: $ids) {
    id
    ... on InventoryItem {
      inventoryLevels(first: 50, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          location { id name }
          quantities(names: ["available", "on_hand", "committed", "incoming", "reserved", "damaged", "safety_stock", "quality_control"]) { name quantity }
        }
      }
    }
  }
}
"""
