"""Fixed, bounded documents for optional catalog export relations."""

IMAGES = """\
query FlowStewardExportImages($ids: [ID!]!, $after: String) {
  nodes(ids: $ids) {
    id
    ... on Product {
      media(first: 50, after: $after, query: "media_type:IMAGE", sortKey: POSITION) {
        pageInfo { hasNextPage endCursor }
        nodes { id alt ... on MediaImage { image { url } } }
      }
    }
  }
}
"""

VARIANTS = """\
query FlowStewardExportVariants($ids: [ID!]!, $after: String, $inventory: Boolean!) {
  nodes(ids: $ids) {
    id
    ... on Product {
      variants(first: 50, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id title sku price compareAtPrice
          selectedOptions { name value }
          inventoryItem @include(if: $inventory) { id tracked }
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
