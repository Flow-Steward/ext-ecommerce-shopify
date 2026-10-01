"""Internal fixed staging and per-row mutation for bulk draft product creation."""

STAGE = """\
mutation FlowStewardStageProductBulk {
  stagedUploadsCreate(input: [{resource: BULK_MUTATION_VARIABLES, filename: "products.jsonl", mimeType: "text/jsonl", httpMethod: POST}]) {
    stagedTargets { url parameters { name value } }
    userErrors { field message }
  }
}
"""

CREATE_ROW = """\
mutation FlowStewardBulkCreateProductRow($product: ProductCreateInput!, $media: [CreateMediaInput!]) {
  productCreate(product: $product, media: $media) {
    product {
      id handle
      variants(first: 1) { nodes { id inventoryItem { id sku } } }
    }
    userErrors { field message }
  }
}
"""
