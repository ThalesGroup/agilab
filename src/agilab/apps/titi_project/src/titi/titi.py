import os
import traceback
import logging
import shutil
import warnings
from pathlib import Path
from typing import Any
import py7zr
import polars as pl
from pydantic import ValidationError
from agi_env import AgiEnv, normalize_path
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher
from .titi_args import TitiArgs, TitiArgsTD, dump_args_to_toml, load_args_from_toml, merge_args
logger = logging.getLogger(__name__)
warnings.filterwarnings('ignore')


class Titi(BaseWorker):
    """Titi class provides methods to orchestrate the run."""
    ivq_logs = None

    def __init__(self, env, args: (TitiArgs | None)=None, **kwargs:
        FlightArgsTD) ->None:
        self.env = env
        if args is None:
            try:
                args = TitiArgs(**kwargs)
            except ValidationError as exc:
                raise ValueError(f'Invalid Titi arguments: {exc}') from exc
        self.args = args
        if AgiEnv._is_managed_pc:
            home = Path.home()
            myapp_home = home / 'MyApp'
            try:
                self.args.data_uri = Path(str(self.args.data_uri).replace(
                    str(home), str(myapp_home)))
            except Exception:
                logger.debug('Failed to remap data_uri for managed PC',
                    exc_info=True)
        if self.args.nfile == 0:
            self.args.nfile = 999999999999
        base_path = Path(env.home_abs) / self.args.data_uri
        normalized_base = Path(normalize_path(base_path))
        self.args.data_uri = normalized_base
        WorkDispatcher.args = self.args.model_dump(mode='json')
        self.data_out = Path(normalize_path(normalized_base / 'dataframe'))
        try:
            if self.data_out.exists():
                shutil.rmtree(self.data_out, ignore_errors=True, onerror=
                    WorkDispatcher._onerror)
            self.data_out.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning(
                'Issue while trying to reset dataframe directory %s: %s',
                self.data_out, exc)

    @classmethod
    def from_toml(cls, env, settings_path: (str | Path)='app_settings.toml',
        section: str='args', **overrides: FlightArgsTD) ->'Titi':
        base_args = load_args_from_toml(settings_path, section)
        merged = merge_args(base_args, overrides or None)
        return cls(env, args=merged)

    def to_toml(self, settings_path: (str | Path)='app_settings.toml',
        section: str='args', create_missing: bool=True) ->None:
        dump_args_to_toml(self.args, settings_path=settings_path, section=
            section, create_missing=create_missing)

    def as_dict(self, mode: str='json') ->dict[str, Any]:
        """Return current arguments as a serialisable dictionary."""
        return self.args.model_dump(mode=mode)

    def build_distribution(self, workers):
        """build_distrib: to provide the list of files per planes (level1) and per workers (level2)
        the level 1 has been think to prevent that à job that requires all the output-data of a plane have to wait for another
        titi_worker which would have collapse the overall performance

        Args:

        Returns:

        """
        try:
            planes_partition, planes_partition_size, df = (self.
                get_partition_by_planes(self.get_data_from_files()))
            workers_chunks = WorkDispatcher.make_chunks(len(
                planes_partition), planes_partition_size, verbose=self.
                verbose, workers=workers, threshold=12)
            if workers_chunks:
                workers_planes_dist = []
                df = df.with_columns([pl.col('id_plane').cast(pl.Int64)])
                for planes in workers_chunks:
                    workers_planes_dist.append([df.filter(pl.col('id_plane'
                        ) == plane_id)['files'].head(self.args.nfile).
                        to_list() for plane_id, _ in planes])
                workers_chunks = [[(plane, round(size / 1000, 3)) for plane,
                    size in chunk] for chunk in workers_chunks]
        except Exception as e:
            print(traceback.format_exc())
            print(f'warning issue while trying to build distribution: {e}')
        return workers_planes_dist, workers_chunks, 'plane', 'files', 'ko'

    def get_data_from_hawk(self):
        """get output-data from ELK/HAWK"""
        pass

    @staticmethod
    def extract_plane_from_file_name(file_path):
        """provide airplane id from log file name

        Args:
          file_path:

        Returns:

        """
        return int(file_path.split('/')[-1].split('_')[2][2:4])

    def get_data_from_files(self):
        """get output-data slices from files or from ELK/HAWK"""
        if self.args.data_source == 'file':
            data_uri = Path(self.args.data_uri)
            home_dir = Path.home()
            self.logs_ivq = {str(f.relative_to(home_dir)): (os.path.getsize
                (f) // 1000) for f in data_uri.rglob(self.args.files) if f.
                is_file()}
            if not self.logs_ivq:
                raise FileNotFoundError(
                    f"Error in make_chunk: no files found with Path('{data_uri}').rglob('{self.args.files}')"
                    )
            df = pl.DataFrame(list(self.logs_ivq.items()), schema=['files',
                'size'])
        elif self.args.data_source == 'hawk':
            pass
        return df

    def get_partition_by_planes(self, df):
        """build the first level of the distribution tree with planes as atomics partition

        Args:
          s: df: dataframe containing the output-data to partition
          df:

        Returns:

        """
        df = df.with_columns(pl.col('files').str.extract(
            '(?:.*/)?(\\d{2})_').cast(pl.Int32).alias('id_plane'))
        df = df.group_by('id_plane').head(self.args.nfile)
        df = df.sort('id_plane')
        planes_partition = df.group_by('id_plane').agg(pl.col('size').sum()
            .alias('size')).sort('size', descending=True)
        planes_partition_size = list(zip(planes_partition['id_plane'].
            to_list(), planes_partition['size'].to_list()))
        return planes_partition, planes_partition_size, df
