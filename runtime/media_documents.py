"""The fixed staging document for image files uploaded from a workflow artifact.

Shopify's documented two-step upload: ``stagedUploadsCreate`` returns a signed
storage target and a ``resourceUrl``; the file is posted to the target, and the
``resourceUrl`` becomes ``originalSource`` in the product mutation. Staging
creates nothing in the store, so it is not an external effect.
"""

STAGE_IMAGES = """\
mutation FlowStewardStageProductImages($input: [StagedUploadInput!]!) {
  stagedUploadsCreate(input: $input) {
    stagedTargets { url resourceUrl parameters { name value } }
    userErrors { field message }
  }
}
"""

#: The staged resource every artifact image is uploaded as.
STAGED_IMAGE_RESOURCE = "IMAGE"

__all__ = ["STAGED_IMAGE_RESOURCE", "STAGE_IMAGES"]
