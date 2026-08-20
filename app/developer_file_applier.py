if action == "create":
    if file_path.exists():
        continue

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )
    file_path.write_text(
        content,
        encoding="utf-8"
    )
    applied.append(change["file"])
