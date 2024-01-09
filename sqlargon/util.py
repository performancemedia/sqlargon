import importlib
from typing import Any

import orjson
from pydantic_core import to_jsonable_python


def json_dumps(data: Any) -> str:
    return orjson.dumps(data, default=to_jsonable_python).decode("utf-8")


def json_loads(data: str) -> Any:
    return orjson.loads(data)


def load_models(packages: str, related_name: str = "models") -> None:
    [find_related_module(pkg, related_name) for pkg in packages]


def find_related_module(package, related_name):
    try:
        module = importlib.import_module(package)
        if not related_name and module:
            return module
    except ImportError:
        package, _, _ = package.rpartition(".")
        if not package:
            raise

    module_name = f"{package}.{related_name}"

    try:
        return importlib.import_module(module_name)
    except ImportError as e:
        import_exc_name = getattr(e, "name", module_name)
        if import_exc_name is not None and import_exc_name != module_name:
            raise e
        return
