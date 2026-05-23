from .app_args import ArgsModel, GlobalDagArgs, dump_args, load_args

__all__ = ["ArgsModel", "GlobalDag", "GlobalDagApp", "GlobalDagArgs", "dump_args", "load_args"]


def __getattr__(name: str):
    if name in {"GlobalDag", "GlobalDagApp"}:
        from .global_dag import GlobalDag, GlobalDagApp

        return {"GlobalDag": GlobalDag, "GlobalDagApp": GlobalDagApp}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
