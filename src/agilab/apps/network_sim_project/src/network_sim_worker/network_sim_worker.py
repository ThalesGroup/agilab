"""Worker entry point for the Network Simulation app."""

from __future__ import annotations

import getpass
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict
from types import SimpleNamespace

import networkx as nx

from agi_env import normalize_path
from agi_node.dag_worker import DagWorker

from network_sim.topology import generate_mixed_topology


class _MutableNamespace(SimpleNamespace):
    """Namespace that also supports item-style access."""

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)


global_vars: Dict[str, Any] = {}


class NetworkSimWorker(DagWorker):  # pragma: no cover - executed within workers
    worker_vars: Dict[str, Any] = {}

    def start(self):
        """Initialize global variables and setup paths."""
        global global_vars

        if not isinstance(self.args, _MutableNamespace):
            if isinstance(self.args, dict):
                payload = self.args
            else:
                payload = vars(self.args)
            self.args = _MutableNamespace(**payload)

        logging.info(f"from: {__file__}")

        if os.name == "nt" and not getpass.getuser().startswith("T0"):
            data_uri = Path(self.args.data_uri)
            parts = data_uri.parts
            if "Users" in parts:
                index = parts.index("Users") + 2
                data_uri = Path(*parts[index:])
            net_path = normalize_path("\\\\127.0.0.1\\" + str(data_uri))
            try:
                # Your NFS account in order to mount it as net drive on Windows
                cmd = f'net use Z: "{net_path}" /user:your-credentials'
                logging.info(cmd)
                subprocess.run(cmd, shell=True, check=True)
            except Exception as e:
                logging.info(f"Failed to map network drive: {e}")

        # Path to database on symlink Path.home()/data(symlink)
        self.home_rel = (Path("~/") / self.args.data_uri).expanduser()
        data_uri = normalize_path(self.home_rel)
        self.data_out = normalize_path(self.home_rel.parent / "dataframe")
        if os.name != "nt":
            self.data_out = self.data_out.replace("\\", "/")

        # Remove dataframe files from previous run
        try:
            shutil.rmtree(self.data_out, ignore_errors=True, onerror=self._onerror)
            os.makedirs(self.data_out, exist_ok=True)
        except Exception as e:
            logging.info(f"Error removing directory: {e}")

        self.args.data_uri = data_uri

        if self.verbose > 1:
            logging.info(f"Worker #{self._worker_id} dataframe root path = {self.data_out}")

        if self.verbose > 0:
            logging.info(f"start worker_id {self._worker_id}\n")
        args = self.args

        if args.data_source == "file":
            # Implement your file logic
            pass
        else:
            # Implement your HAWK logic
            pass

        self.pool_vars["args"] = self.args
        self.pool_vars["verbose"] = self.verbose
        global global_vars
        global_vars = self.pool_vars

    def pool_init(self, worker_vars: Dict[str, Any]) -> None:  # pragma: no cover - template hook
        global global_vars
        global_vars = worker_vars

    def work_pool(self, file) -> Dict[str, Any]:
        global global_vars
        args_namespace = global_vars.get("args")
        if args_namespace is None:
            params: Dict[str, Any] = {}
        elif isinstance(args_namespace, dict):
            params = dict(args_namespace)
            args_namespace = _MutableNamespace(**params)
            global_vars["args"] = args_namespace
        else:
            params = dict(vars(args_namespace))

        net_size = int(params.get("net_size", 12))
        seed = params.get("seed")
        topology_filename = params.get("topology_filename", "topology.gml")
        summary_filename = params.get("summary_filename", "topology_summary.json")
        data_source = params.get("data_source", "file")

        data_uri_value = params.get("data_uri")
        if not data_uri_value:
            raise ValueError("Missing data_uri in worker arguments")
        data_uri = Path(data_uri_value)

        prefix = "~/"
        if data_source == "file":
            if os.name != "nt":
                file = os.path.normpath(os.path.expanduser(prefix + file)).replace(
                    "\\", "/"
                )
            else:
                file = normalize_path(os.path.expanduser(prefix + file))

            if not Path(file).is_file():
                raise FileNotFoundError(file)

        graph = generate_mixed_topology(net_size, seed=seed)

        topology_path = data_uri / topology_filename
        topology_path.parent.mkdir(parents=True, exist_ok=True)
        nx.write_gml(graph, topology_path)

        summary = {
            "net_size": net_size,
            "seed": seed,
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "topology_file": str(topology_path),
        }

        summary_path = data_uri / summary_filename
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        return summary
