"""Deterministic tests for the tool-call argument normalisation helper."""

from __future__ import annotations

import json
import pytest

from app.tool_call_args import ArgumentNormalizationError, normalize_tool_arguments


class DescribeNormalizeToolArguments:
    # ------------------------------------------------------------------
    # Already a dict
    # ------------------------------------------------------------------
    def test_dict_returned_unchanged(self):
        original = {"key": "value", "nested": {"a": 1}}
        result = normalize_tool_arguments(original)
        assert result is original  # object identity preserved

    def test_empty_dict_returned_unchanged(self):
        original = {}
        result = normalize_tool_arguments(original)
        assert result == {}

    # ------------------------------------------------------------------
    # String – valid JSON object
    # ------------------------------------------------------------------
    def test_json_object_string_parsed_to_dict(self):
        s = '{"project_id": "abc", "plan": true}'
        result = normalize_tool_arguments(s)
        assert result == {"project_id": "abc", "plan": True}

    def test_json_object_string_with_null_values(self):
        s = '{"a": null, "b": "text"}'
        result = normalize_tool_arguments(s)
        assert result == {"a": None, "b": "text"}  # null becomes None *inside* dict

    # ------------------------------------------------------------------
    # String – JSON null / empty
    # ------------------------------------------------------------------
    def test_json_null_returns_empty_dict(self):
        assert normalize_tool_arguments("null") == {}

    # ------------------------------------------------------------------
    # String – invalid JSON (array, bool, number, string)
    # ------------------------------------------------------------------
    @pytest.mark.parametrize(
        "invalid_json",
        [
            "[]",
            "true",
            "false",
            "42",
            '"just a string"',
        ],
    )
    def test_non_object_json_raises(self, invalid_json):
        with pytest.raises(ArgumentNormalizationError):
            normalize_tool_arguments(invalid_json)

    # ------------------------------------------------------------------
    # String – invalid JSON syntax
    # ------------------------------------------------------------------
    def test_malformed_json_raises(self):
        with pytest.raises(ArgumentNormalizationError):
            normalize_tool_arguments("{this is not json}")

    # ------------------------------------------------------------------
    # Other invalid types
    # ------------------------------------------------------------------
    @pytest.mark.parametrize(
        "bad_input",
        [
            None,
            True,
            False,
            42,
            3.14,
            [],
            (),
            {1, 2},
        ],
    )
    def test_non_dict_non_string_raises(self, bad_input):
        with pytest.raises(ArgumentNormalizationError):
            normalize_tool_arguments(bad_input)

    # ------------------------------------------------------------------
    # String - JSON string with leading/trailing whitespace
    # ------------------------------------------------------------------
    def test_json_object_with_whitespace(self):
        s = '  { "x": 1 }  '
        result = normalize_tool_arguments(s)
        assert result == {"x": 1}

    # ------------------------------------------------------------------
    # String - JSON object with escaped characters
    # ------------------------------------------------------------------
    def test_escaped_chars_in_json_string(self):
        s = r'{"message": "hello \"world\"\n"}'
        result = normalize_tool_arguments(s)
        assert result == {"message": 'hello "world"\n'}
