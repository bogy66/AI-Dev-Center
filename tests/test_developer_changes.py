import json
import pytest
from app.developer_changes import DeveloperChanges


# =========================================================================
# Legacy Markdown compatibility (unchanged)
# =========================================================================

def test_parse_developer_changes():
    response = """
## Analyse

Neue Funktion.

## Dateien

### Datei:
app/example.py

### Aktion:
update

### Inhalt:
print("hello")

## Tests

python -m pytest -q
"""

    result = DeveloperChanges.parse(response)

    assert result["changes"][0]["file"] == "app/example.py"
    assert result["changes"][0]["action"] == "update"
    assert result["changes"][0]["content"] == 'print("hello")'


def test_parse_multiple_changes():
    response = """
## Dateien

### Datei:
app/a.py

### Aktion:
update

### Inhalt:
print("a")

### Datei:
app/b.py

### Aktion:
create

### Inhalt:
print("b")

## Tests

python -m pytest -q
"""

    result = DeveloperChanges.parse(response)

    assert len(result["changes"]) == 2
    assert result["changes"][0]["file"] == "app/a.py"
    assert result["changes"][0]["action"] == "update"
    assert result["changes"][1]["file"] == "app/b.py"
    assert result["changes"][1]["action"] == "create"


def test_parse_delete_change():
    response = """
## Dateien

### Datei:
app/old.py

### Aktion:
delete

## Tests
"""

    result = DeveloperChanges.parse(response)

    assert result["changes"][0]["file"] == "app/old.py"
    assert result["changes"][0]["action"] == "delete"
    assert result["changes"][0]["content"] == ""


def test_parse_rejects_invalid_action():
    response = """
## Dateien

### Datei:
app/example.py

### Aktion:
execute

### Inhalt:
print("hello")
"""

    result = DeveloperChanges.parse(response)

    assert result["changes"] == []


def test_parse_rejects_path_traversal():
    response = """
## Dateien

### Datei:
../../outside.py

### Aktion:
update

### Inhalt:
print("hello")
"""

    result = DeveloperChanges.parse(response)

    assert result["changes"] == []


def test_parse_empty_response_raises_error():
    with pytest.raises(ValueError) as exc_info:
        DeveloperChanges.parse("")

    assert "empty or non-string" in str(exc_info.value)


def test_parse_none_response_raises_error():
    with pytest.raises(ValueError) as exc_info:
        DeveloperChanges.parse(None)

    assert "empty or non-string" in str(exc_info.value)


def test_parse_missing_dateien_section_raises_error():
    response = """
## Analyse

Keine Dateien hier.

## Tests

python -m pytest -q
"""

    with pytest.raises(ValueError) as exc_info:
        DeveloperChanges.parse(response)

    assert "missing '## Dateien' section" in str(exc_info.value)


def test_parse_valid_response_with_no_changes():
    response = """
## Dateien

## Tests

python -m pytest -q
"""

    result = DeveloperChanges.parse(response)

    assert result["changes"] == []
    assert result["tests"] == ["python -m pytest -q"]


# =========================================================================
# Structured JSON contract tests
# =========================================================================


def _valid_create():
    return json.dumps({
        "changes": [{"file": "app/main.py", "action": "create", "content": "print(1)"}],
        "tests": ["pytest"],
    })


def _valid_update():
    return json.dumps({
        "changes": [{"file": "app/main.py", "action": "update", "content": "print(2)"}],
        "tests": ["pytest", "black --check app/"],
    })


def _valid_delete():
    return json.dumps({
        "changes": [{"file": "app/old.py", "action": "delete", "content": ""}],
        "tests": ["pytest"],
    })


# 1. valid create
def test_structured_valid_create():
    result = DeveloperChanges.parse_structured(_valid_create())
    assert len(result["changes"]) == 1
    assert result["changes"][0]["file"] == "app/main.py"
    assert result["changes"][0]["action"] == "create"
    assert result["changes"][0]["content"] == "print(1)"
    assert result["tests"] == ["pytest"]


# 2. valid update
def test_structured_valid_update():
    result = DeveloperChanges.parse_structured(_valid_update())
    assert result["changes"][0]["action"] == "update"
    assert result["tests"] == ["pytest", "black --check app/"]


# 3. valid delete
def test_structured_valid_delete():
    result = DeveloperChanges.parse_structured(_valid_delete())
    assert result["changes"][0]["action"] == "delete"
    assert result["changes"][0]["content"] == ""


# 4. multiple changes
def test_structured_multiple_changes():
    response = json.dumps({
        "changes": [
            {"file": "a.py", "action": "create", "content": "a"},
            {"file": "b.py", "action": "update", "content": "b"},
            {"file": "c.py", "action": "delete", "content": ""},
        ],
        "tests": ["t1", "t2"],
    })
    result = DeveloperChanges.parse_structured(response)
    assert len(result["changes"]) == 3
    assert len(result["tests"]) == 2


# 5. tests array preserved
def test_structured_tests_preserved():
    result = DeveloperChanges.parse_structured(_valid_update())
    assert result["tests"] == ["pytest", "black --check app/"]


# 6. invalid JSON rejected
def test_structured_invalid_json_rejected():
    with pytest.raises(ValueError, match="not valid JSON"):
        DeveloperChanges.parse_structured("not json")


# 7. non-object root rejected
def test_structured_non_object_root_rejected():
    with pytest.raises(ValueError, match="root must be a JSON object"):
        DeveloperChanges.parse_structured(json.dumps([{"file": "a.py"}]))


# 8. missing changes rejected
def test_structured_missing_changes_rejected():
    with pytest.raises(ValueError, match="'changes' must be an array"):
        DeveloperChanges.parse_structured(json.dumps({"tests": ["pytest"]}))


# 8b. invalid changes type
def test_structured_changes_not_array_rejected():
    with pytest.raises(ValueError, match="'changes' must be an array"):
        DeveloperChanges.parse_structured(json.dumps({"changes": "not-array", "tests": []}))


# 9. missing tests rejected
def test_structured_missing_tests_rejected():
    with pytest.raises(ValueError, match="'tests' must be an array"):
        DeveloperChanges.parse_structured(json.dumps({
            "changes": [{"file": "a.py", "action": "create", "content": "x"}],
        }))


# 9b. invalid tests type
def test_structured_tests_not_array_rejected():
    with pytest.raises(ValueError, match="'tests' must be an array"):
        DeveloperChanges.parse_structured(json.dumps({
            "changes": [], "tests": "not-array",
        }))


# 9c. test entry not string
def test_structured_test_entry_not_string_rejected():
    with pytest.raises(ValueError, match="'tests' entries must be strings"):
        DeveloperChanges.parse_structured(json.dumps({
            "changes": [], "tests": [1, 2, 3],
        }))


# 10. absolute path rejected
def test_structured_absolute_path_rejected():
    with pytest.raises(ValueError, match="invalid or unsafe file path"):
        DeveloperChanges.parse_structured(json.dumps({
            "changes": [{"file": "/etc/passwd", "action": "create", "content": "x"}],
            "tests": [],
        }))


# 11. path traversal rejected
def test_structured_path_traversal_rejected():
    with pytest.raises(ValueError, match="invalid or unsafe file path"):
        DeveloperChanges.parse_structured(json.dumps({
            "changes": [{"file": "../../outside.py", "action": "create", "content": "x"}],
            "tests": [],
        }))


# 12. invalid action rejects the whole structured response
def test_structured_invalid_action_rejects_whole_response():
    with pytest.raises(ValueError, match="unsupported action"):
        DeveloperChanges.parse_structured(json.dumps({
            "changes": [{"file": "a.py", "action": "execute", "content": "x"}],
            "tests": [],
        }))


# 13. invalid change entry rejects the whole response
def test_structured_invalid_entry_rejects_whole_response():
    with pytest.raises(ValueError, match="unsupported action"):
        DeveloperChanges.parse_structured(json.dumps({
            "changes": [
                {"file": "ok.py", "action": "create", "content": "x"},
                {"file": "bad.py", "action": "rm -rf", "content": "x"},
            ],
            "tests": [],
        }))


# 13b. non-dict entry rejects response
def test_structured_non_dict_entry_rejected():
    with pytest.raises(ValueError, match="each change must be an object"):
        DeveloperChanges.parse_structured(json.dumps({
            "changes": ["not-a-dict"],
            "tests": [],
        }))


# 14. no partial acceptance
def test_structured_no_partial_acceptance():
    with pytest.raises(ValueError):
        DeveloperChanges.parse_structured(json.dumps({
            "changes": [
                {"file": "a.py", "action": "create", "content": "ok"},
                {"file": "bad", "action": "create"},
            ],
            "tests": [],
        }))


# 14b. missing content rejected
def test_structured_missing_content_rejected():
    with pytest.raises(ValueError, match="missing required 'content' field"):
        DeveloperChanges.parse_structured(json.dumps({
            "changes": [{"file": "a.py", "action": "create"}],
            "tests": [],
        }))


# 14c. content not string rejected
def test_structured_content_not_string_rejected():
    with pytest.raises(ValueError, match="'content' must be a string"):
        DeveloperChanges.parse_structured(json.dumps({
            "changes": [{"file": "a.py", "action": "create", "content": 123}],
            "tests": [],
        }))


# 15. empty response rejected
def test_structured_empty_response_rejected():
    with pytest.raises(ValueError, match="empty or non-string"):
        DeveloperChanges.parse_structured("")


# 15b. None response rejected
def test_structured_none_response_rejected():
    with pytest.raises(ValueError, match="empty or non-string"):
        DeveloperChanges.parse_structured(None)


# 16. empty changes array is valid
def test_structured_empty_changes_valid():
    result = DeveloperChanges.parse_structured(json.dumps({
        "changes": [], "tests": ["lint"],
    }))
    assert result["changes"] == []
    assert result["tests"] == ["lint"]


# =========================================================================
# Legacy Markdown compatibility still works
# =========================================================================

def test_legacy_parse_still_works():
    """DeveloperChanges.parse() remains available for legacy callers."""
    response = "## Dateien\n### Datei: app/main.py\nupdate\n### Inhalt:\nx"
    result = DeveloperChanges.parse(response)
    assert result["changes"][0]["file"] == "app/main.py"
    assert result["changes"][0]["action"] == "update"
    assert result["changes"][0]["content"] == "x"


def test_legacy_parse_empty_sections():
    result = DeveloperChanges.parse("## Dateien\n## Tests\npytest -q")
    assert result["changes"] == []
    assert result["tests"] == ["pytest -q"]


def test_legacy_parse_compact_format():
    response = "## Dateien\n### Datei: a.py\ncreate\n### Inhalt:\ncontent"
    result = DeveloperChanges.parse(response)
    assert result["changes"][0]["file"] == "a.py"
    assert result["changes"][0]["action"] == "create"
    assert result["changes"][0]["content"] == "content"