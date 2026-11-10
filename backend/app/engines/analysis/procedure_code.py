"""Run a procedure the analyst supplied, with no imports or file access."""

import ast
from typing import Any

import numpy as np
import pandas as pd
import scipy
import sklearn
import statsmodels.api as sm
from sklearn.cluster import DBSCAN, AgglomerativeClustering, KMeans, SpectralClustering
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

from app.errors import AppError

_MAX_CHARS = 12000
_FORBIDDEN_NAMES = {
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
_FORBIDDEN_ATTRS = {
    "read_csv",
    "read_excel",
    "read_parquet",
    "read_pickle",
    "read_json",
    "read_sql",
    "read_html",
    "read_xml",
    "read_feather",
    "read_stata",
    "read_spss",
    "to_pickle",
    "to_csv",
    "to_excel",
    "to_json",
    "to_sql",
    "to_parquet",
    "save",
    "load",
    "loadtxt",
    "savetxt",
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
}
_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "map": map,
    "filter": filter,
    "pow": pow,
    "reversed": reversed,
    "isinstance": isinstance,
}


def validate_procedure(source: str) -> None:
    """Reject a procedure that is not a plain ``compute`` function.

    Args:
        source: Python source. It must define ``compute(data, seed)``.

    Raises:
        AppError: The source is empty, too long, or uses a blocked operation.
    """
    text = source.strip()
    if not text:
        raise AppError("The procedure is empty, so no result was published.", "bad_plan")
    if len(text) > _MAX_CHARS:
        raise AppError("The procedure is too long to run.", "bad_plan")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise AppError(
            "The procedure could not be read as Python, so no result was published.",
            "bad_plan",
        ) from exc
    names = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "compute"
    ]
    if len(names) != 1:
        raise AppError(
            "The procedure must define compute(data, seed). No result was published.",
            "bad_plan",
        )
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef)):
            raise AppError(
                "The procedure cannot import or define a class. No result was published.",
                "bad_plan",
            )
        if isinstance(node, ast.Name) and (node.id in _FORBIDDEN_NAMES or node.id.startswith("_")):
            raise AppError(
                "The procedure uses a blocked operation. No result was published.",
                "bad_plan",
            )
        if isinstance(node, ast.Attribute) and (
            node.attr in _FORBIDDEN_ATTRS or node.attr.startswith("_")
        ):
            raise AppError(
                "The procedure uses a blocked operation. No result was published.",
                "bad_plan",
            )


def run_procedure(source: str, data: pd.DataFrame, seed: int) -> dict[str, Any]:
    """Execute ``compute`` on the prepared frame.

    Args:
        source: Procedure source that already passed ``validate_procedure``.
        data: Prepared numeric columns.
        seed: Random seed.

    Returns:
        The dictionary ``compute`` returned.

    Raises:
        AppError: The procedure raises or does not return a dictionary.
    """
    validate_procedure(source)
    namespace: dict[str, Any] = {
        "__builtins__": _BUILTINS,
        "np": np,
        "pd": pd,
        "scipy": scipy,
        "sklearn": sklearn,
        "sm": sm,
        "KMeans": KMeans,
        "AgglomerativeClustering": AgglomerativeClustering,
        "DBSCAN": DBSCAN,
        "SpectralClustering": SpectralClustering,
        "GaussianMixture": GaussianMixture,
        "StandardScaler": StandardScaler,
        "silhouette_score": silhouette_score,
    }
    try:
        exec(compile(source, "<procedure>", "exec"), namespace)  # noqa: S102
        returned = namespace["compute"](data, seed)
    except AppError:
        raise
    except Exception as exc:
        detail = str(exc).strip().splitlines()[-1] if str(exc).strip() else exc.__class__.__name__
        raise AppError(
            f"The procedure failed ({detail[:240]}). No result was published.",
            "sandbox_failed",
        ) from exc
    if not isinstance(returned, dict):
        raise AppError(
            "The procedure did not return its computed fields. No result was published.",
            "bad_plan",
        )
    return returned
