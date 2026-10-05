"""Map validated operation input onto Shopify's own input objects, field by field.

Only keys the caller actually sent are added, so an omitted field is left alone
rather than overwritten with an empty value. Each table below pairs one of this
extension's snake_case fields with the Shopify field it fills; the coverage
tests compare the variables these produce with the official input types.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from . import documents

#: The option and value Shopify gives a product created without options.
DEFAULT_OPTION_NAME = "Title"
DEFAULT_OPTION_VALUE = "Default Title"

_Pairs = Sequence[tuple[str, str]]


def _copy(source: Mapping[str, Any], pairs: _Pairs) -> dict[str, Any]:
    return {target: source[name] for name, target in pairs if name in source}


def _each(
    source: Mapping[str, Any], name: str, build: Callable[[Mapping[str, Any]], Any]
) -> list[Any] | None:
    items = source.get(name)
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return None
    return [build(item) for item in items]


# -- Shared pieces ---------------------------------------------------------


def metafield_input(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Shopify ``MetafieldInput``."""
    return _copy(
        entry,
        (("id", "id"), ("namespace", "namespace"), ("key", "key"), ("type", "type"),
         ("value", "value")),
    )  # fmt: skip


def _seo(source: Mapping[str, Any], built: dict[str, Any]) -> None:
    seo = _copy(source, (("seo_title", "title"), ("seo_description", "description")))
    if seo:
        built["seo"] = seo


_PRODUCT_FIELDS: _Pairs = (
    ("title", "title"),
    ("handle", "handle"),
    ("description_html", "descriptionHtml"),
    ("vendor", "vendor"),
    ("product_type", "productType"),
    ("category_id", "category"),
    ("template_suffix", "templateSuffix"),
    ("gift_card_template_suffix", "giftCardTemplateSuffix"),
    ("requires_selling_plan", "requiresSellingPlan"),
    ("status", "status"),
)


def product_input(operation_input: Mapping[str, Any]) -> dict[str, Any]:
    """The product fields creation and update share."""
    built = _copy(operation_input, _PRODUCT_FIELDS)
    _seo(operation_input, built)
    return built


# -- Media -----------------------------------------------------------------


def file_set_input(item: Mapping[str, Any]) -> dict[str, Any]:
    """Shopify ``FileSetInput``: a file by URL or by existing id."""
    built = _copy(
        item,
        (
            ("source_url", "originalSource"),
            ("file_id", "id"),
            ("alt", "alt"),
            ("filename", "filename"),
            ("duplicate_resolution_mode", "duplicateResolutionMode"),
        ),
    )
    if "content_type" in item:
        built["contentType"] = item["content_type"]
    return built


def create_media_input(item: Mapping[str, Any]) -> dict[str, Any]:
    """Shopify ``CreateMediaInput``."""
    built = {
        "originalSource": item["source_url"],
        "mediaContentType": item.get("content_type", "IMAGE"),
    }
    if "alt" in item:
        built["alt"] = item["alt"]
    return built


def staged_file_set_input(staged: Mapping[str, Any]) -> dict[str, Any]:
    """A ``FileSetInput`` for an image already uploaded to Shopify's staging."""
    built: dict[str, Any] = {"originalSource": staged["resource_url"], "contentType": "IMAGE"}
    built.update(_copy(staged, (("alt", "alt"), ("filename", "filename"))))
    return built


def staged_create_media_input(staged: Mapping[str, Any]) -> dict[str, Any]:
    built: dict[str, Any] = {
        "originalSource": staged["resource_url"],
        "mediaContentType": "IMAGE",
    }
    if "alt" in staged:
        built["alt"] = staged["alt"]
    return built


# -- Variants --------------------------------------------------------------


def _option_values(entry: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    def build(value: Mapping[str, Any]) -> dict[str, Any]:
        return _copy(
            value,
            (
                ("option_name", "optionName"),
                ("value", "name"),
                ("linked_metafield_value", "linkedMetafieldValue"),
            ),
        )

    return _each(entry, "option_values", build)


def inventory_item_input(item: Mapping[str, Any], *, with_sku: bool = True) -> dict[str, Any]:
    """Shopify ``InventoryItemInput``."""
    pairs: list[tuple[str, str]] = [
        ("cost", "cost"),
        ("tracked", "tracked"),
        ("requires_shipping", "requiresShipping"),
        ("country_code_of_origin", "countryCodeOfOrigin"),
        ("province_code_of_origin", "provinceCodeOfOrigin"),
        ("harmonized_system_code", "harmonizedSystemCode"),
    ]
    if with_sku:
        pairs.insert(0, ("sku", "sku"))
    built = _copy(item, pairs)
    codes = _each(
        item,
        "country_harmonized_system_codes",
        lambda code: _copy(
            code,
            (("harmonized_system_code", "harmonizedSystemCode"), ("country_code", "countryCode")),
        ),
    )
    if codes is not None:
        built["countryHarmonizedSystemCodes"] = codes
    measurement = item.get("measurement")
    if isinstance(measurement, Mapping):
        measured: dict[str, Any] = {}
        weight = measurement.get("weight")
        if isinstance(weight, Mapping):
            measured["weight"] = {"value": weight["value"], "unit": weight["unit"]}
        if "shipping_package_id" in measurement:
            measured["shippingPackageId"] = measurement["shipping_package_id"]
        built["measurement"] = measured
    return built


_VARIANT_COMMON: _Pairs = (
    ("price", "price"),
    ("compare_at_price", "compareAtPrice"),
    ("barcode", "barcode"),
    ("inventory_policy", "inventoryPolicy"),
    ("taxable", "taxable"),
    ("tax_code", "taxCode"),
    ("requires_components", "requiresComponents"),
    ("published", "published"),
    ("show_unit_price", "showUnitPrice"),
)


def _variant_common(entry: Mapping[str, Any], *, inventory_sku: bool) -> dict[str, Any]:
    built = _copy(entry, _VARIANT_COMMON)
    measurement = entry.get("unit_price_measurement")
    if isinstance(measurement, Mapping):
        built["unitPriceMeasurement"] = _copy(
            measurement,
            (
                ("quantity_value", "quantityValue"),
                ("quantity_unit", "quantityUnit"),
                ("reference_value", "referenceValue"),
                ("reference_unit", "referenceUnit"),
            ),
        )
    item = entry.get("inventory_item")
    if isinstance(item, Mapping) and item:
        built["inventoryItem"] = inventory_item_input(item, with_sku=inventory_sku)
    return built


def variant_bulk_input(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Shopify ``ProductVariantsBulkInput``, for the variant batch operations."""
    built = _variant_common(entry, inventory_sku=True)
    if "variant_id" in entry:
        built["id"] = entry["variant_id"]
    option_values = _option_values(entry)
    if option_values is not None:
        built["optionValues"] = option_values
    if "media_src" in entry:
        built["mediaSrc"] = list(entry["media_src"])
    if "media_id" in entry:
        built["mediaId"] = entry["media_id"]
    quantities = _each(
        entry,
        "inventory_quantities",
        lambda q: {"locationId": q["location_id"], "availableQuantity": q["available_quantity"]},
    )
    if quantities is not None:
        built["inventoryQuantities"] = quantities
    adjustments = _each(
        entry,
        "quantity_adjustments",
        lambda q: {
            "locationId": q["location_id"],
            "adjustment": q.get("adjustment"),
            "changeFromQuantity": q["change_from_quantity"],
        },
    )
    if adjustments is not None:
        built["quantityAdjustments"] = adjustments
    metafields = _each(entry, "metafields", metafield_input)
    if metafields is not None:
        built["metafields"] = metafields
    return built


def variant_set_input(
    entry: Mapping[str, Any], option_values: list[dict[str, Any]]
) -> dict[str, Any]:
    """Shopify ``ProductVariantSetInput``, for a variant created with its product.

    ``sku`` travels on the variant itself; ``productSet`` would accept the same
    value on the inventory item too, and sending it twice could only disagree.
    """
    built = _variant_common(entry, inventory_sku=False)
    built["optionValues"] = option_values
    built.update(_copy(entry, (("sku", "sku"), ("position", "position"))))
    image = entry.get("image")
    if isinstance(image, Mapping):
        built["file"] = {**file_set_input(image), "contentType": "IMAGE"}
    quantities = _each(
        entry,
        "inventory_quantities",
        lambda q: {"locationId": q["location_id"], "name": q["name"], "quantity": q["quantity"]},
    )
    if quantities is not None:
        built["inventoryQuantities"] = quantities
    metafields = _each(entry, "metafields", metafield_input)
    if metafields is not None:
        built["metafields"] = metafields
    return built


# -- Products --------------------------------------------------------------


def _product_options(options: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    built: list[dict[str, Any]] = []
    for option in options:
        entry: dict[str, Any] = {"name": option["name"]}
        if "position" in option:
            entry["position"] = option["position"]
        if "values" in option:
            entry["values"] = [{"name": value} for value in option["values"]]
        linked = option.get("linked_metafield")
        if isinstance(linked, Mapping):
            entry["linkedMetafield"] = _copy(
                linked, (("namespace", "namespace"), ("key", "key"), ("values", "values"))
            )
        built.append(entry)
    return built


def _initial_option_values(options: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The option values of the one variant built when none is given.

    The first value of each option, exactly as ``productCreate`` would choose.
    """
    chosen: list[dict[str, Any]] = []
    for option in options:
        linked = option.get("linked_metafield")
        if isinstance(linked, Mapping):
            chosen.append(
                {"optionName": option["name"], "linkedMetafieldValue": linked["values"][0]}
            )
        else:
            chosen.append({"optionName": option["name"], "name": option["values"][0]})
    return chosen


def product_set_input(
    operation_input: Mapping[str, Any], *, staged_images: Sequence[Mapping[str, Any]] = ()
) -> dict[str, Any]:
    """Shopify ``ProductSetInput`` for a brand-new product.

    Options and variants are always explicit. Shopify's ``productSet`` needs
    both together, so a product without options gets Shopify's own single
    ``Title`` / ``Default Title`` option, and a product without variants gets
    the one variant ``productCreate`` would have built.
    """
    built = product_input(operation_input)
    built.setdefault("status", documents.CREATE_PRODUCT_STATUS)
    if "tags" in operation_input:
        built["tags"] = list(operation_input["tags"])
    built.update(
        _copy(
            operation_input,
            (
                ("gift_card", "giftCard"),
                ("combined_listing_role", "combinedListingRole"),
            ),
        )
    )
    if "collection_ids" in operation_input:
        built["collections"] = list(operation_input["collection_ids"])
    claim = operation_input.get("claim_ownership")
    if isinstance(claim, Mapping):
        built["claimOwnership"] = _copy(claim, (("bundles", "bundles"),))
    metafields = _each(operation_input, "metafields", metafield_input)
    if metafields is not None:
        built["metafields"] = metafields

    options = list(operation_input.get("options") or [])
    if not options:
        options = [{"name": DEFAULT_OPTION_NAME, "values": [DEFAULT_OPTION_VALUE]}]
    built["productOptions"] = _product_options(options)

    variants = list(operation_input.get("variants") or [])
    if not variants:
        variants = [{}]
    built["variants"] = [
        variant_set_input(
            entry,
            _option_values(entry) or _initial_option_values(options),
        )
        for entry in variants
    ]

    files = [file_set_input(item) for item in operation_input.get("media") or []]
    files.extend(staged_file_set_input(image) for image in staged_images)
    if files:
        built["files"] = files
    return built


def create_product_variables(
    operation_input: Mapping[str, Any], *, staged_images: Sequence[Mapping[str, Any]] = ()
) -> dict[str, Any]:
    """Variables for the ``productSet`` creation document."""
    product = product_set_input(operation_input, staged_images=staged_images)
    return {"input": product, "variantsFirst": len(product["variants"])}


def product_update_variables(
    operation_input: Mapping[str, Any], *, staged_images: Sequence[Mapping[str, Any]] = ()
) -> dict[str, Any]:
    """Variables for ``productUpdate``: the product, its new media, its identifier."""
    product = product_input(operation_input)
    if "product_id" in operation_input:
        product["id"] = operation_input["product_id"]
    if "replace_tags" in operation_input:
        product["tags"] = list(operation_input["replace_tags"])
    if "handle" in operation_input:
        product["redirectNewHandle"] = operation_input.get("redirect_new_handle", True)
    if "category_id" in operation_input:
        product["deleteConflictingConstrainedMetafields"] = operation_input.get(
            "delete_conflicting_constrained_metafields", False
        )
    if "join_collection_ids" in operation_input:
        product["collectionsToJoin"] = list(operation_input["join_collection_ids"])
    if "leave_collection_ids" in operation_input:
        product["collectionsToLeave"] = list(operation_input["leave_collection_ids"])
    metafields = _each(operation_input, "metafields", metafield_input)
    if metafields is not None:
        product["metafields"] = metafields

    variables: dict[str, Any] = {"product": product, "media": None, "identifier": None}
    media = [create_media_input(item) for item in operation_input.get("media") or []]
    media.extend(staged_create_media_input(image) for image in staged_images)
    if media:
        variables["media"] = media
    if "product_handle" in operation_input:
        variables["identifier"] = {"handle": operation_input["product_handle"]}
    elif "product_custom_id" in operation_input:
        variables["identifier"] = {
            "customId": _copy(
                operation_input["product_custom_id"],
                (("namespace", "namespace"), ("key", "key"), ("value", "value")),
            )
        }
    return variables


__all__ = [
    "DEFAULT_OPTION_NAME",
    "DEFAULT_OPTION_VALUE",
    "create_media_input",
    "create_product_variables",
    "file_set_input",
    "inventory_item_input",
    "metafield_input",
    "product_input",
    "product_set_input",
    "product_update_variables",
    "variant_bulk_input",
    "variant_set_input",
]
