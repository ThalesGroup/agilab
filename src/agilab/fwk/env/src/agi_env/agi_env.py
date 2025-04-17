# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
# following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the
#    following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the
#    following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS,
#    may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
# USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import ast
import cmd
import asyncio
import getpass
import os
import subprocess
import threading
import queue
import traceback
import time
import re
import sys
from pathlib import Path, PureWindowsPath, PurePosixPath
from dotenv import dotenv_values, set_key
from pathspec import PathSpec


class JumpToMain(Exception):
    """
    Custom exception to jump back to the main execution flow.
    """
    pass

class ContentRenamer(ast.NodeTransformer):
    """
    A class that renames identifiers in an abstract syntax tree (AST).
    Attributes:
        rename_map (dict): A mapping of old identifiers to new identifiers.
    """
    def __init__(self, rename_map):
        self.rename_map = rename_map
    # ... (all visit_* methods unchanged) ...

class AgiEnv:
    """
    AgiEnv manages paths and environment variables within the agiFramework.
    """
    install_type = None
    apps_dir = None
    app = None
    module = None

    def __init__(self, install_type: int=None, apps_dir: Path=None, active_app: Path|str=None,
                 active_module: Path=None, verbose: int=0):
        # ... (initialization code unchanged) ...
        pass

    def create_rename_map(self, target_project: Path, dest_project: Path) -> dict:
        """
        Create a mapping of old → new names for cloning.
        Includes project names, top-level src folders, worker folders,
        in-file identifiers and class names.
        """
        def cap(s: str) -> str:
            return "".join(p.capitalize() for p in s.split("_"))

        name_tp = target_project.name      # e.g. "flight_project"
        name_dp = dest_project.name        # e.g. "tata_project"
        tp = name_tp[:-8]                  # strip "_project" → "flight"
        dp = name_dp[:-8]                  # → "tata"

        tm = tp.replace("-", "_")
        dm = dp.replace("-", "_")
        tc = cap(tm)                       # "Flight"
        dc = cap(dm)                       # "Tata"

        return {
            # project-level
            name_tp:              name_dp,

            # folder-level (longest keys first)
            f"src/{tm}_worker": f"src/{dm}_worker",
            f"src/{tm}":        f"src/{dm}",

            # sibling-level
            f"{tm}_worker":      f"{dm}_worker",
            tm:                    dm,

            # class-level
            f"{tc}Worker":       f"{dc}Worker",
            f"{tc}Args":         f"{dc}Args",
            tc:                    dc,
        }

    def clone_project(self, target_project: Path, dest_project: Path):
        """
        Clone a project by copying files and directories, applying renaming,
        then cleaning up any leftovers.

        Args:
            target_project: Path under self.apps_dir (e.g. Path("flight_project"))
            dest_project:   Path under self.apps_dir (e.g. Path("tata_project"))
        """
        # Lazy import heavy deps
        import shutil, ast, os, astor
        from pathspec import PathSpec
        from pathspec.patterns import GitWildMatchPattern

        # normalize names
        if not target_project.name.endswith("_project"):
            target_project = target_project.with_name(target_project.name + "_project")
        if not dest_project.name.endswith("_project"):
            dest_project = dest_project.with_name(dest_project.name + "_project")

        rename_map  = self.create_rename_map(target_project, dest_project)
        source_root = self.apps_dir / target_project
        dest_root   = self.apps_dir / dest_project

        if not source_root.exists():
            print(f"Source project '{target_project}' does not exist.")
            return
        if dest_root.exists():
            print(f"Destination project '{dest_project}' already exists.")
            return

        gitignore = source_root / ".gitignore"
        if not gitignore.exists():
            print(f"No .gitignore at '{gitignore}'.")
            return
        spec = PathSpec.from_lines(GitWildMatchPattern, gitignore.read_text().splitlines())

        try:
            dest_root.mkdir(parents=True, exist_ok=False)
        except Exception as e:
            print(f"Could not create '{dest_root}': {e}")
            return

        # 1) Recursive clone
        self.clone_directory(source_root, dest_root, rename_map, spec, source_root)

        # 2) Final cleanup
        self._cleanup_rename(dest_root, rename_map)

    def clone_directory(self,
                        source_dir: Path,
                        dest_dir: Path,
                        rename_map: dict,
                        spec: "PathSpec",  # ← quoted
                        source_root: Path):
        """
        Recursively copy + rename:
         - explicit src/<mod> and src/<mod>_worker directory swaps
         - then generic old→new on paths
         - then AST/text content rewriting
        """
        import shutil, os, ast, astor

        tm = source_root.name[:-8]
        dp = dest_dir.name[:-8]
        tm_mod = tm.replace("-", "_")
        dp_mod = dp.replace("-", "_")

        for item in source_dir.iterdir():
            rel = item.relative_to(source_root).as_posix()
            if spec.match_file(rel + ("/" if item.is_dir() else "")):
                continue

            # 1) folder swap
            parts = rel.split("/")
            if len(parts) >= 2 and parts[0] == "src":
                if parts[1] == tm_mod:
                    parts[1] = dp_mod
                elif parts[1] == f"{tm_mod}_worker":
                    parts[1] = f"{dp_mod}_worker"
            new_rel = "/".join(parts)

            # 2) generic map
            for old, new in sorted(rename_map.items(), key=lambda kv: len(kv[0]), reverse=True):
                new_rel = new_rel.replace(old, new)

            dest_item = dest_dir / Path(new_rel)

            if item.is_dir() and item.name == ".venv":
                self.handle_venv_directory(item, dest_item)
                continue

            if item.is_dir():
                dest_item.mkdir(parents=True, exist_ok=True)
                self.clone_directory(item, dest_dir, rename_map, spec, source_root)

            elif item.is_file():
                if dest_item.exists():
                    continue
                suf = item.suffix.lower()
                if suf in (".7z", ".zip"): shutil.copy2(item, dest_item)
                elif suf == ".py":
                    src = item.read_text(encoding="utf-8")
                    try:
                        tree = ast.parse(src)
                        renamer = ContentRenamer(rename_map)
                        new_t = renamer.visit(tree)
                        ast.fix_missing_locations(new_t)
                        dest_item.write_text(astor.to_source(new_t), encoding="utf-8")
                    except SyntaxError:
                        shutil.copy2(item, dest_item)
                else:
                    txt = item.read_text(encoding="utf-8")
                    for old, new in rename_map.items(): txt = txt.replace(old, new)
                    dest_item.write_text(txt, encoding="utf-8")

            elif item.is_symlink():
                os.symlink(os.readlink(item), dest_item, target_is_directory=item.is_dir())

    def _cleanup_rename(self, root: Path, rename_map: dict):
        """
        1) Rename any leftover file/dir names containing old keys.
        2) Rewrite text files to replace any leftover old→new in contents.
        """
        # filesystem names
        for old, new in sorted(rename_map.items(), key=lambda kv: len(kv[0]), reverse=True):
            for path in list(root.rglob(f"*{old}*")):
                path.rename(path.with_name(path.name.replace(old, new)))

        # contents
        exts = {".py", ".toml", ".md", ".txt", ".json", ".yaml", ".yml"}
        for file in root.rglob("*"):
            if not file.is_file() or file.suffix.lower() not in exts: continue
            text = file.read_text(encoding="utf-8")
            newt = text
            for old, new in rename_map.items(): newt = newt.replace(old, new)
            if newt != text: file.write_text(newt, encoding="utf-8")

    def read_gitignore(self, gitignore_path: Path) -> 'PathSpec':
        from pathspec import PathSpec
        from pathspec.patterns import GitWildMatchPattern
        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        return PathSpec.from_lines(GitWildMatchPattern, lines)

    # ... (remaining methods unchanged) ...
