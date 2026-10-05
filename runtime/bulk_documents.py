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
mutation FlowStewardBulkCreateProductRow($input: ProductSetInput!) {
  productSet(input: $input) {
    product { id handle }
    userErrors { code field message }
  }
}
"""
