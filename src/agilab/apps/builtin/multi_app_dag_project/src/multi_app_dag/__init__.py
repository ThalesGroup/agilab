from .app_args import ArgsModel, MultiAppDagArgs, dump_args, load_args

__all__ = ["ArgsModel", "MultiAppDag", "MultiAppDagApp", "MultiAppDagArgs", "dump_args", "load_args"]


def __getattr__(name: str):
    if name in {"MultiAppDag", "MultiAppDagApp"}:
        from .multi_app_dag import MultiAppDag, MultiAppDagApp

        return {"MultiAppDag": MultiAppDag, "MultiAppDagApp": MultiAppDagApp}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
