"""Reject an analysis script that is not a plain scientific program."""

import ast

from app.errors import AppError

_MAX_CHARS = 20000
_ALLOWED_ROOTS = frozenset(
    {
        "numpy",
        "pandas",
        "scipy",
        "sklearn",
        "statsmodels",
        "math",
        "statistics",
        "json",
        "pathlib",
    }
)
_FORBIDDEN_NAMES = frozenset(
    {
        "open",
        "exec",
        "eval",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "input",
        "breakpoint",
        "help",
        "exit",
        "quit",
        "memoryview",
    }
)
_FORBIDDEN_ATTRS = frozenset(
    {
        "system",
        "popen",
        "remove",
        "unlink",
        "rmtree",
        "mkdir",
        "chmod",
        "getenv",
        "putenv",
        "listdir",
        "scandir",
        "walk",
        "startfile",
        "open",
    }
)


def validate_program(source: str, dataset_columns: set[str], declared: set[str]) -> None:
    """Reject a script that leaves the allowed scientific surface.

    Args:
        source: Python source the sandbox would execute.
        dataset_columns: Column names on the dataset.
        declared: Column names the plan said the script may read.

    Raises:
        AppError: The script is empty, too long, imports a blocked module,
            calls a blocked operation, or names a column the plan left out.
    """
    text = source.strip()
    if not text:
        raise AppError("The analysis script is empty, so no result was published.", "bad_plan")
    if len(text) > _MAX_CHARS:
        raise AppError("The analysis script is too long to run.", "bad_plan")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise AppError(
            "The analysis script could not be read as Python, so no result was published.",
            "bad_plan",
        ) from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _allow_module(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise AppError(
                    "The analysis script imports a module it cannot use. No result was published.",
                    "bad_plan",
                )
            _allow_module(node.module or "")
        elif isinstance(node, ast.Name) and (
            node.id in _FORBIDDEN_NAMES or node.id.startswith("__")
        ):
            raise AppError(
                "The analysis script uses a blocked operation. No result was published.",
                "bad_plan",
            )
        elif isinstance(node, ast.Attribute) and (
            node.attr in _FORBIDDEN_ATTRS or node.attr.startswith("__")
        ):
            raise AppError(
                "The analysis script uses a blocked operation. No result was published.",
                "bad_plan",
            )
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in dataset_columns
            and node.value not in declared
        ):
            raise AppError(
                f"The analysis script names {node.value}, which the plan did not include. "
                "No result was published.",
                "bad_plan",
            )


def _allow_module(name: str) -> None:
    """Reject an import whose top-level package is not on the scientific list.

    Args:
        name: Dotted module name from an import statement.

    Raises:
        AppError: The package is not one the script may import.
    """
    root = name.split(".", 1)[0]
    if root not in _ALLOWED_ROOTS:
        label = root or "a relative module"
        raise AppError(
            f"The analysis script imports {label}, which it cannot use. No result was published.",
            "bad_plan",
        )
