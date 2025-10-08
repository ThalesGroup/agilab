# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import os
import sys
import argparse
from pathlib import Path
import parso


def _ensure_agi_env() -> None:
    """Make sure the :mod:`agi_env` package can be imported in source layouts."""

    try:
        from agi_env import AgiEnv  # noqa: F401  # pragma: no cover
        return
    except ModuleNotFoundError:
        pass

    script_path = Path(__file__).resolve()
    candidates: list[Path] = []

    path_parents = list(script_path.parents)
    for offset in range(len(path_parents)):
        root = path_parents[offset]
        candidates.extend(
            [
                root / "agi-env/src",
                root / "core/agi-env/src",
                root / "agilab/core/agi-env/src",
            ]
        )

    for candidate in candidates:
        package_dir = candidate / "agi_env"
        if package_dir.exists() and package_dir.is_dir():
            sys.path.insert(0, str(candidate))
            sys.modules.pop("agi_env", None)
            from agi_env import AgiEnv  # noqa: F401  # pragma: no cover
            return

    raise ModuleNotFoundError(
        "Unable to locate the agi_env package required by pre_install.py"
    )


_ensure_agi_env()
from agi_env import AgiEnv


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
        if expr.type == 'atom_expr':
            names = [child.value for child in expr.children if child.type ==
                'name']
            if names:
                return names[-1]
        elif expr.type == 'name':
            return expr.value
    return decorator_node.get_code()


def process_decorators(node, decorator_names, verbose=False):
    """
    Removes decorators from the given node if they match any in decorator_names.
    """
    decorators = node.get_decorators()
    for decorator in list(decorators):
        name = get_decorator_name(decorator)
        AgiEnv.log_info(
            f"Found decorator: @{name} on {node.type} '{node.name.value}'")
        if name in decorator_names:
            AgiEnv.log_info(
                f"Removing decorator: @{name} from {node.type} '{node.name.value}'"
                )
            parent = decorator.parent
            try:
                index = parent.children.index(decorator)
                parent.children.remove(decorator)
                if index < len(parent.children) and parent.children[index
                    ].type == 'newline':
                    parent.children.pop(index)
                AgiEnv.log_info(f'Decorator @{name} removed.')
            except ValueError:
                AgiEnv.log_info(
                    f"Decorator @{name} not found in parent's children.")


def remove_decorators(source_code, decorator_names=None, verbose=True):
    """
    Removes specified decorators from the given Python source code.
    """
    if decorator_names is None:
        decorator_names = []
    tree = parso.parse(source_code)

    def traverse(node):
        for child in list(node.children):
            if child.type in ('funcdef', 'async_funcdef', 'classdef'):
                if verbose > 2:
                    AgiEnv.log_info(
                        f"Processing {child.type} '{child.name.value}'")
                process_decorators(child, decorator_names, verbose)
                traverse(child)
            elif hasattr(child, 'children'):
                traverse(child)
    traverse(tree)
    return tree.get_code()


def prepare_for_cython(args):
    """
    Prepares the worker source file for Cython by removing specified decorators.
    """
    worker_path = Path(args.worker_path)
    cython_src = worker_path.with_suffix(args.cython_target_src_ext)
    with open(cython_src, 'r') as file:
        source = file.read()
    modified_source = remove_decorators(source, verbose=args.verbose)
    cython_out = worker_path.with_suffix('.pyx')
    with open(cython_out, 'w') as file:
        file.write(modified_source)
    AgiEnv.log_info(f'Processed {cython_src} and generated {cython_out}')


def main():
    parser = argparse.ArgumentParser(description=
        'Utility for Cython preparation.')
    subparsers = parser.add_subparsers(dest='command', required=True)
    remove_parser = subparsers.add_parser('remove_decorators', help=
        'Remove decorators from the worker source file for Cython compilation.'
        )
    remove_parser.add_argument('--worker_path', required=True, help=
        'Path to the worker source file.')
    remove_parser.add_argument('--cython_target_src_ext', default='.py',
        help='Target source file extension (default: .py).')
    remove_parser.add_argument('--verbose', action='store_true', help=
        'Enable verbose output.')
    remove_parser.set_defaults(func=prepare_for_cython)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
