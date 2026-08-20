result = subprocess.run(
    "python -m py_compile app/*.py",
    cwd=project,
    shell=True,
    ...
)
