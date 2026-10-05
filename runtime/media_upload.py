"""Upload workflow-artifact images to Shopify before a product mutation uses them.

Shopify's documented two-step flow: ``stagedUploadsCreate`` issues one signed
storage target per file, each file is posted to its target, and the returned
``resourceUrl`` becomes the image's ``originalSource`` in the product mutation.
Staging changes nothing in the store — an image that is staged but never
attached is discarded by Shopify — so a failure here is always a definite "no
change was made".

Every file is read and checked before anything is staged: an unreadable,
oversized or non-image artifact fails the whole call up front instead of
leaving half the images uploaded.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from flowsteward_extension_sdk import find_artifact_descriptor, open_pinned_url, read_artifact_bytes

from . import errors, media_documents, shapes
from .bulk_storage import staged_resource_url, upload_staged
from .errors import ExtensionError

#: Shopify's product image limits: 20 MB a file.
MAX_IMAGE_BYTES = 20 * 1024 * 1024

#: The image formats Shopify accepts for product media, by their file signature.
_SIGNATURES: tuple[tuple[bytes, int, str, str], ...] = (
    (b"\xff\xd8\xff", 0, "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", 0, "image/png", "png"),
    (b"GIF87a", 0, "image/gif", "gif"),
    (b"GIF89a", 0, "image/gif", "gif"),
    (b"WEBP", 8, "image/webp", "webp"),
)
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_BINDING_KEY = "product_image_files"


def _invalid(message: str) -> ExtensionError:
    return ExtensionError(errors.INVALID_PAYLOAD, message, definitely_no_external_effect=True)


def _image_type(body: bytes) -> tuple[str, str] | None:
    for signature, offset, mime_type, extension in _SIGNATURES:
        if body[offset : offset + len(signature)] == signature:
            if mime_type == "image/webp" and body[:4] != b"RIFF":
                continue
            return mime_type, extension
    return None


def _filename(requested: Any, descriptor: Mapping[str, Any], index: int, extension: str) -> str:
    raw = requested if isinstance(requested, str) and requested.strip() else ""
    if not raw:
        for key in ("filename", "name"):
            value = descriptor.get(key)
            if isinstance(value, str) and value.strip():
                raw = value
                break
    stem = _UNSAFE_FILENAME.sub("-", raw.rsplit("/", 1)[-1]).strip(".-")[:200]
    if not stem:
        stem = f"image-{index + 1}"
    if "." not in stem:
        stem = f"{stem}.{extension}"
    return stem


def _read(
    payload: Mapping[str, Any], entry: Mapping[str, Any], index: int, reader: Callable[..., Any]
) -> dict[str, Any]:
    handle = str(entry["artifact_handle"])
    field = f"image_files[{index}]"
    try:
        body = reader(dict(payload), artifact_id=handle)
    except ExtensionError:
        raise
    except Exception as exc:
        raise _invalid(f"{field} could not be read from Flow Steward storage") from exc
    if not isinstance(body, (bytes, bytearray)) or not body:
        raise _invalid(f"{field} is empty")
    if len(body) > MAX_IMAGE_BYTES:
        raise _invalid(f"{field} is larger than Shopify's 20 MB image limit")
    detected = _image_type(bytes(body[:16]))
    if detected is None:
        raise _invalid(f"{field} is not a JPEG, PNG, GIF or WEBP image")
    mime_type, extension = detected
    try:
        descriptor = find_artifact_descriptor(dict(payload), artifact_id=handle)
    except Exception:
        descriptor = {}
    return {
        "body": bytes(body),
        "mime_type": mime_type,
        "filename": _filename(entry.get("filename"), descriptor, index, extension),
        "alt": entry.get("alt"),
    }


def stage_images(
    payload: Mapping[str, Any],
    transport: Any,
    image_files: Sequence[Mapping[str, Any]],
    *,
    reader: Callable[..., Any] | None = None,
    opener: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """Read, check and stage every image; return what the mutation attaches."""
    if not image_files:
        return []
    files = [
        _read(payload, entry, index, reader or read_artifact_bytes)
        for index, entry in enumerate(image_files)
    ]
    data = transport.execute(
        media_documents.STAGE_IMAGES,
        {
            "input": [
                {
                    "resource": media_documents.STAGED_IMAGE_RESOURCE,
                    "filename": file["filename"],
                    "mimeType": file["mime_type"],
                    "fileSize": str(len(file["body"])),
                    "httpMethod": "POST",
                }
                for file in files
            ]
        },
        mutating=False,
        purpose="Shopify product image staging",
    ).data
    staged = shapes.mapping(data.get("stagedUploadsCreate"))
    targets = staged.get("stagedTargets")
    if (
        staged.get("userErrors")
        or not isinstance(targets, list)
        or len(targets) != len(files)
        or not all(isinstance(target, Mapping) for target in targets)
    ):
        raise ExtensionError(
            errors.UPSTREAM_VALIDATION_FAILED,
            "Shopify did not provide a staged upload for every image",
            definitely_no_external_effect=True,
        )
    attached: list[dict[str, Any]] = []
    for file, target in zip(files, targets, strict=True):
        resource_url = staged_resource_url(target.get("resourceUrl"))
        upload_staged(
            target,
            file["body"],
            filename=file["filename"],
            content_type=file["mime_type"],
            key_marker="/",
            purpose="Shopify product image staged upload",
            opener=opener or open_pinned_url,
        )
        image: dict[str, Any] = {"resource_url": resource_url, "filename": file["filename"]}
        if isinstance(file["alt"], str):
            image["alt"] = file["alt"]
        attached.append(image)
    return attached


__all__ = ["MAX_IMAGE_BYTES", "stage_images"]
