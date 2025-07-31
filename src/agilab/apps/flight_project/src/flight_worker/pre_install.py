import os
import sys
import argparse
from pathlib import Path
import parso
import logging
from agi_env import AgiEnv, normalize_path


def get_decorator_name(decorator_node):
    """
    Extracts the base name of the decorator.

    For example:
        '@decorator'         -> 'decorator'
        '@decorator(arg)'    -> 'decorator'
        '@module.decorator'  -> 'decorator'
    """
    if len(decorator_node.children) >= 2:
        expr = decorator_node.children[1]
        if expr.type == "atom_expr":
            names = [child.value for child in expr.children if child.type == "name"]
            if names:
                return names[-1]
        elif expr.type == "name":
            return expr.value
    return decorator_node.get_code()


def process_decorators(node, decorator_names, verbose=False):
    """
    Removes decorators from the given node if they match any in decorator_names.
    """
    decorators = node.get_decorators()
    for decorator in list(decorators):
        name = get_decorator_name(decorator)
        logging.info(f"Found decorator: @{name} on {node.type} '{node.name.value}'")
        if name in decorator_names:
            logging.info(f"Removing decorator: @{name} from {node.type} '{node.name.value}'")
            parent = decorator.parent  # The decorator list node
            try:
                index = parent.children.index(decorator)
                parent.children.remove(decorator)
                # Remove trailing newline if present
                if index < len(parent.children) and parent.children[index].type == "newline":
                    parent.children.pop(index)
                logging.info(f"Decorator @{name} removed.")
            except ValueError:
                logging.error(f"Decorator @{name} not found in parent's children.")


def remove_decorators(source_code, decorator_names=None, verbose=True):
    """
    Removes specified decorators from the given Python source code.
    """
    # Provide a default empty list if none specified.
    if decorator_names is None:
        decorator_names = []

    tree = parso.parse(source_code)

    def traverse(node):
        for child in list(node.children):
            if child.type in ("funcdef", "async_funcdef", "classdef"):
                if verbose>2:
                    logging.info(f"Processing {child.type} '{child.name.value}'")
                process_decorators(child, decorator_names, verbose)
                traverse(child)
            elif hasattr(child, "children"):
                traverse(child)

    traverse(tree)
    return tree.get_code()


def prepare_for_cython(args):
    """
    Prepares the worker source file for Cython by removing specified decorators.
    """
    worker_path = Path(args.worker_path)
    # Change the suffix for the source file to process
    cython_src = worker_path.with_suffix(args.cython_target_src_ext)

    with open(cython_src, "r") as file:
        source = file.read()

    modified_source = remove_decorators(source, verbose=args.verbose)

    # Write the modified code to a new .pyx file
    cython_out = worker_path.with_suffix('.pyx')
    with open(cython_out, "w") as file:
        file.write(modified_source)

    logging.info(f"Processed {cython_src} and generated {cython_out}")


def main():
    # logging.info("Within venv", sys.prefix)
    # logging.info("run Cython preprocessing...\n", __file__)
    parser = argparse.ArgumentParser(description="Utility for Cython preparation.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    remove_parser = subparsers.add_parser(
        "remove_decorators",
        help="Remove decorators from the worker source file for Cython compilation."
    )
    remove_parser.add_argument(
        "--worker_path", required=True,
        help="Path to the worker source file."
    )
    remove_parser.add_argument(
        "--cython_target_src_ext", default=".py",
        help="Target source file extension (default: .py)."
    )
    remove_parser.add_argument(
        "--verbose", action="store_true",
        help="Enable verbose output."
    )
    remove_parser.set_defaults(func=prepare_for_cython)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()