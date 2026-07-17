"""Metaclass support for the ``AgiEnv`` singleton compatibility layer."""

import inspect


class AgiEnvMeta(type):
    """Delegate class attribute access to the singleton instance."""

    def __call__(cls, *args, **kwargs):  # type: ignore[override]
        """Keep singleton allocation and initialization under one bounded guard."""

        try:
            construction_guard = type.__getattribute__(
                cls, "_bounded_construction_guard"
            )
        except AttributeError:
            return super().__call__(*args, **kwargs)
        with construction_guard():
            return super().__call__(*args, **kwargs)

    def __getattribute__(cls, name):  # type: ignore[override]
        if name in {"_instance", "_lock", "current", "reset", "__dict__", "__weakref__"}:
            return super().__getattribute__(name)

        found_on_class = False
        try:
            obj = super().__getattribute__(name)
            found_on_class = True
            if (
                inspect.isfunction(obj)
                or inspect.ismethoddescriptor(obj)
                or isinstance(obj, (property, staticmethod, classmethod, type))
            ):
                return obj
        except AttributeError:
            obj = None

        try:
            inst = super().__getattribute__("_instance")
        except AttributeError:
            inst = None
        if inst is not None and hasattr(inst, name):
            return getattr(inst, name)

        if found_on_class:
            return obj
        raise AttributeError(f"type object '{cls.__name__}' has no attribute '{name}'")

    def __setattr__(cls, name, value):  # type: ignore[override]
        if name in {"_instance", "_lock"} or (name.startswith("__") and name.endswith("__")):
            return super().__setattr__(name, value)

        if (
            inspect.isfunction(value)
            or inspect.ismethoddescriptor(value)
            or isinstance(value, (property, staticmethod, classmethod, type))
        ):
            return super().__setattr__(name, value)
        inst = getattr(cls, "_instance", None)
        if inst is not None:
            setattr(inst, name, value)
        else:
            super().__setattr__(name, value)
