from app.developer_changes import DeveloperChanges
import pytest

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
