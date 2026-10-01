"""The published schema is executed, not decorative.

The reason this module exists at all: a nested ``required`` list that the
platform never runs is worse than no declaration, because the author believes
the contract is enforced. Everything below proves the rules the manifest
publishes are the rules the runtime applies.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from runtime import schema
from runtime.catalog import OPERATIONS, OPERATIONS_BY_ID
from runtime.errors import ExtensionError

QUANTITIES = OPERATIONS_BY_ID["set_inventory_quantities"].input_schema


def _errors(value: object, declared: dict) -> str:
    with pytest.raises(ExtensionError) as raised:
        schema.validate(value, declared)
    return raised.value.message


class TestOnlyExecutableKeywordsAreAccepted:
    def test_the_two_keyword_sets_do_not_overlap(self) -> None:
        assert not (schema.EXECUTED_KEYWORDS & schema.ANNOTATION_KEYWORDS)

    def test_a_keyword_this_module_would_not_run_is_named(self) -> None:
        findings = schema.unsupported_schema_keywords({"type": "string", "pattern": "^gid://"})

        assert findings == ["schema.pattern"]

    def test_the_refusal_reaches_nested_positions(self) -> None:
        findings = schema.unsupported_schema_keywords(
            {"type": "object", "properties": {"a": {"type": "array", "uniqueItems": True}}}
        )

        assert findings == ["schema.properties.a.uniqueItems"]

    def test_it_reaches_into_array_items(self) -> None:
        findings = schema.unsupported_schema_keywords(
            {"type": "array", "items": {"type": "string", "format": "uri", "pattern": "x"}}
        )

        assert findings == ["schema.items.pattern"]

    def test_annotations_assert_nothing_and_are_allowed(self) -> None:
        assert not schema.unsupported_schema_keywords(
            {"type": "string", "title": "t", "description": "d", "default": "x"}
        )

    @pytest.mark.parametrize("row", OPERATIONS, ids=lambda row: row.operation_id)
    def test_no_shipped_operation_declares_an_unexecutable_rule(self, row) -> None:
        assert not schema.unsupported_schema_keywords(row.input_schema)


class TestTheKeywordSetsMatchTheHosts:
    """Restated here rather than imported: an extension may not read core.

    If the platform's own subset changes, these literals are what fails, which
    is the point: an operation must never declare a rule the host would ignore,
    and must never be refused here for a rule the host would happily execute.
    """

    HOST_EXECUTED: ClassVar[set[str]] = {
        "type",
        "enum",
        "const",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
        "oneOf",
        "anyOf",
        "allOf",
        "if",
        "then",
        "else",
        "dependentRequired",
    }
    HOST_ANNOTATIONS: ClassVar[set[str]] = {
        "$schema",
        "$id",
        "$comment",
        "title",
        "description",
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "format",
    }

    def test_this_module_executes_no_keyword_the_host_would_not(self) -> None:
        assert schema.EXECUTED_KEYWORDS <= self.HOST_EXECUTED

    def test_the_annotations_are_exactly_the_hosts(self) -> None:
        assert schema.ANNOTATION_KEYWORDS == self.HOST_ANNOTATIONS

    def test_a_keyword_the_host_executes_but_this_module_does_not_is_still_refused(
        self,
    ) -> None:
        """Conditional keywords are deliberately not used by this extension."""
        unsupported = self.HOST_EXECUTED - schema.EXECUTED_KEYWORDS

        assert unsupported == {"oneOf", "anyOf", "allOf", "if", "then", "else", "dependentRequired"}
        for keyword in unsupported:
            assert schema.unsupported_schema_keywords({"type": "object", keyword: []})


class TestTypes:
    @pytest.mark.parametrize(
        ("value", "declared"),
        [
            ("x", {"type": "string"}),
            (1, {"type": "integer"}),
            (1.5, {"type": "number"}),
            (1, {"type": "number"}),
            (True, {"type": "boolean"}),
            (None, {"type": "null"}),
            ([], {"type": "array"}),
            ({}, {"type": "object"}),
            (None, {"type": ["integer", "null"]}),
            (3, {"type": ["integer", "null"]}),
        ],
    )
    def test_a_matching_value_is_accepted(self, value: object, declared: dict) -> None:
        schema.validate(value, declared)

    @pytest.mark.parametrize(
        ("value", "declared"),
        [
            (1, {"type": "string"}),
            ("1", {"type": "integer"}),
            (True, {"type": "integer"}),
            (True, {"type": "number"}),
            (1, {"type": "boolean"}),
            (1.5, {"type": "integer"}),
            ("x", {"type": "array"}),
            ([], {"type": "object"}),
            (None, {"type": "string"}),
            ("x", {"type": ["integer", "null"]}),
        ],
    )
    def test_a_mismatched_value_is_refused(self, value: object, declared: dict) -> None:
        _errors(value, declared)

    def test_a_boolean_is_never_an_integer(self) -> None:
        """Python says ``True == 1``; a stock quantity of ``True`` is nonsense."""
        _errors(True, {"type": "integer"})

    def test_an_integer_is_never_a_boolean(self) -> None:
        """And ``1`` is not "yes": a flag supplied as a number is refused.

        Both directions matter. `taxable: 1` and `quantity: True` are each a
        caller confusing a flag with a count, and Python's own truthiness would
        let either through if the check were a plain isinstance.
        """
        _errors(1, {"type": "boolean"})
        _errors(0, {"type": "boolean"})

    def test_the_two_directions_hold_through_a_real_operation(self) -> None:
        from runtime.catalog import OPERATIONS_BY_ID

        row = OPERATIONS_BY_ID["list_locations"]

        _errors({"connection_ref": "c", "include_inactive": 1}, row.input_schema)
        _errors({"connection_ref": "c", "first": True}, row.input_schema)


class TestBounds:
    @pytest.mark.parametrize(
        ("value", "declared"),
        [
            ("", {"type": "string", "minLength": 1}),
            ("abc", {"type": "string", "maxLength": 2}),
            (0, {"type": "integer", "minimum": 1}),
            (251, {"type": "integer", "maximum": 250}),
            ([], {"type": "array", "minItems": 1}),
            ([1, 2], {"type": "array", "maxItems": 1}),
        ],
    )
    def test_a_value_outside_its_bounds_is_refused(self, value: object, declared: dict) -> None:
        _errors(value, declared)

    @pytest.mark.parametrize(
        ("value", "declared"),
        [
            ("a", {"type": "string", "minLength": 1}),
            (1, {"type": "integer", "minimum": 1, "maximum": 250}),
            (250, {"type": "integer", "minimum": 1, "maximum": 250}),
            ([1], {"type": "array", "minItems": 1, "maxItems": 1}),
        ],
    )
    def test_a_value_at_its_bounds_is_accepted(self, value: object, declared: dict) -> None:
        schema.validate(value, declared)


class TestObjects:
    def test_a_missing_required_field_is_named(self) -> None:
        message = _errors({"a": 1}, {"type": "object", "required": ["a", "b"], "properties": {}})

        assert "b" in message

    def test_an_undeclared_field_is_refused(self) -> None:
        message = _errors(
            {"a": 1, "z": 2},
            {"type": "object", "additionalProperties": False, "properties": {"a": {}}},
        )

        assert "z" in message

    def test_a_nested_object_is_checked_against_its_own_rules(self) -> None:
        declared = {
            "type": "object",
            "properties": {
                "inner": {
                    "type": "object",
                    "required": ["needed"],
                    "properties": {"needed": {"type": "integer"}},
                }
            },
        }

        message = _errors({"inner": {}}, declared)

        assert "inner.needed" in message

    def test_it_refuses_a_payload_nested_beyond_the_limit(self) -> None:
        declared: dict = {"type": "object"}
        node = declared
        for _ in range(schema.MAX_PAYLOAD_DEPTH + 2):
            node["properties"] = {"n": {"type": "object"}}
            node = node["properties"]["n"]
        value: dict = {}
        node_value = value
        for _ in range(schema.MAX_PAYLOAD_DEPTH + 2):
            node_value["n"] = {}
            node_value = node_value["n"]

        assert "too deeply" in _errors(value, declared)


class TestTheShippedQuantityContract:
    """The nested rules the task calls out by name, run against the real schema."""

    def _payload(self, quantities: object) -> dict:
        return {"connection_ref": "c1", "quantities": quantities}

    def test_an_entry_with_no_fields_fails_locally(self) -> None:
        assert "inventory_item_id is required" in _errors(self._payload([{}]), QUANTITIES)

    @pytest.mark.parametrize(
        "missing", ["inventory_item_id", "location_id", "quantity", "change_from_quantity"]
    )
    def test_each_nested_field_is_required_in_its_own_right(self, missing: str) -> None:
        entry = {
            "inventory_item_id": "gid://shopify/InventoryItem/1",
            "location_id": "gid://shopify/Location/1",
            "quantity": 1,
            "change_from_quantity": None,
        }
        del entry[missing]

        assert missing in _errors(self._payload([entry]), QUANTITIES)

    def test_a_nested_additional_property_is_refused(self) -> None:
        entry = {
            "inventory_item_id": "gid://shopify/InventoryItem/1",
            "location_id": "gid://shopify/Location/1",
            "quantity": 1,
            "change_from_quantity": None,
            "compare_quantity": 3,
        }

        assert "compare_quantity" in _errors(self._payload([entry]), QUANTITIES)

    def test_an_outer_additional_property_is_refused(self) -> None:
        payload = {**self._payload([]), "ignore_compare_quantity": True}

        assert "ignore_compare_quantity" in _errors(payload, QUANTITIES)

    def test_the_batch_bounds_are_the_published_ones(self) -> None:
        quantities = QUANTITIES["properties"]["quantities"]

        assert quantities["minItems"] == 1
        assert quantities["maxItems"] == 250
        assert "1 item" in _errors(self._payload([]), QUANTITIES)

    def test_an_explicit_null_compare_value_is_accepted(self) -> None:
        entry = {
            "inventory_item_id": "gid://shopify/InventoryItem/1",
            "location_id": "gid://shopify/Location/1",
            "quantity": 1,
            "change_from_quantity": None,
        }

        schema.validate(self._payload([entry]), QUANTITIES)

    def test_an_integer_compare_value_is_accepted(self) -> None:
        entry = {
            "inventory_item_id": "gid://shopify/InventoryItem/1",
            "location_id": "gid://shopify/Location/1",
            "quantity": 1,
            "change_from_quantity": 4,
        }

        schema.validate(self._payload([entry]), QUANTITIES)
