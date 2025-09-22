import getpass
import glob
import os
import re
import shutil
import subprocess
import traceback
import warnings
from datetime import datetime as dt
from pathlib import Path
import logging
from types import SimpleNamespace
from agi_env import normalize_path
from agi_node.polars_worker import PolarsWorker
from agi_node.agi_dispatcher import BaseWorker
logger = logging.getLogger(__name__)
warnings.filterwarnings('ignore')
import polars as pl
from geopy.distance import geodesic


class _MutableNamespace(SimpleNamespace):
    """Namespace that also supports item-style access."""

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)


class TitiWorker(PolarsWorker):
    """Class derived from AgiDataWorker"""
    pool_vars = {}

    def preprocess_df(self, df: pl.DataFrame) ->pl.DataFrame:
        """
        Preprocess the DataFrame by parsing the date column and creating
        previous coordinate columns. This operation is done once per file.
        """
        df = df.with_columns([pl.col('date').str.strptime(pl.Datetime,
            format='%Y-%m-%d %H:%M:%S').alias('date'), pl.col('lat').shift(
            1).alias('prev_lat'), pl.col('long').shift(1).alias('prev_long')])
        return df

    def calculate_speed(self, new_column_name: str, df: pl.DataFrame
        ) ->pl.DataFrame:
        """
        Compute the speed (in meters) between consecutive coordinate pairs
        and add it to the DataFrame under the provided column name.
        Assumes that the previous coordinate columns are already present.
        """
        df = df.with_columns([pl.struct(['prev_lat', 'prev_long', 'lat',
            'long']).map_elements(lambda row: 0 if row['prev_lat'] is None else
            geodesic((row['prev_lat'], row['prev_long']), (row['lat'], row[
            'long'])).meters, return_dtype=pl.Float64).alias(new_column_name)])
        return df

    def start(self):
        """Initialize global variables and setup paths."""
        global global_vars
        if not isinstance(self.args, _MutableNamespace):
            if isinstance(self.args, dict):
                payload = self.args
            else:
                payload = vars(self.args)
            self.args = _MutableNamespace(**payload)
        logging.info(f'from: {__file__}')
        if os.name == 'nt' and not getpass.getuser().startswith('T0'):
            data_uri = Path(self.args.data_uri)
            parts = data_uri.parts
            if 'Users' in parts:
                index = parts.index('Users') + 2
                data_uri = Path(*parts[index:])
            net_path = normalize_path('\\\\127.0.0.1\\' + str(data_uri))
            try:
                cmd = f'net use Z: "{net_path}" /user:your-credentials'
                logging.info(cmd)
                subprocess.run(cmd, shell=True, check=True)
            except Exception as e:
                logging.info(f'Failed to map network drive: {e}')
        self.home_rel = (Path('~/') / self.args.data_uri).expanduser()
        data_uri = normalize_path(self.home_rel)
        self.data_out = normalize_path(self.home_rel.parent / 'dataframe')
        if os.name != 'nt':
            self.data_out = self.data_out.replace('\\', '/')
        try:
            shutil.rmtree(self.data_out, ignore_errors=True, onerror=self.
                _onerror)
            os.makedirs(self.data_out, exist_ok=True)
        except Exception as e:
            logging.info(f'Error removing directory: {e}')
        self.args['data_uri'] = data_uri
        if self.verbose > 1:
            logging.info(
                f'Worker #{self._worker_id} dataframe root path = {self.data_out}'
                )
        if self.verbose > 0:
            logging.info(f'start worker_id {self._worker_id}\n')
        args = self.args
        if args['data_source'] == 'file':
            pass
        else:
            pass
        self.pool_vars['args'] = self.args
        self.pool_vars['verbose'] = self.verbose
        global_vars = self.pool_vars

    def work_init(self):
        """Initialize work by reading from shared space."""
        global global_vars
        pass

    def pool_init(self, worker_vars):
        """Initialize the pool with worker variables.

        Args:
            worker_vars (dict): Variables specific to the worker.

        """
        global global_vars
        global_vars = worker_vars

    def work_pool(self, file):
        """Parse IVQ log files.

        Args:
            file (str): The log file to parse.

        Returns:
            pl.DataFrame: Parsed data.
        """
        global global_vars
        data_source = global_vars['args']['data_source']
        prefix = '~/'
        if data_source == 'file':
            if os.name != 'nt':
                file = os.path.normpath(os.path.expanduser(prefix + file)
                    ).replace('\\', '/')
            else:
                file = normalize_path(os.path.expanduser(prefix + file))
            if not Path(file).is_file():
                raise FileNotFoundError(file)
        df = pl.read_csv(file)
        if df.columns and (df.columns[0].startswith('Unnamed') or df.
            columns[0] == ''):
            df = df.drop(df.columns[0])
        df = self.preprocess_df(df)
        if 'lat' in df.columns and 'long' in df.columns:
            df = df.with_columns([pl.col('lat').shift(1).alias('prev_lat'),
                pl.col('long').shift(1).alias('prev_long')])
        df = self.calculate_speed('speed', df)
        return df

    def work_done(self, worker_df):
        """Concatenate dataframe if any and save the results.

        Args:
            worker_df (pl.DataFrame): Output dataframe for one plane.

        """
        if worker_df.is_empty():
            return
        os.makedirs(self.data_out, exist_ok=True)
        for plane in worker_df.select(pl.col('aircraft')).unique().to_series():
            plane_df = worker_df.filter(pl.col('aircraft') == plane).sort(
                'date')
            plane_df = plane_df.with_columns(pl.col('aircraft').alias(
                'worker_id'))
            try:
                if self.args['output_format'] == 'parquet':
                    filename = (Path(self.data_out) / str(plane)).with_suffix(
                        '.parquet')
                    plane_df.write_parquet(str(filename))
                elif self.args['output_format'] == 'csv':
                    timestamp = dt.now().strftime('%Y-%m-%d_%H-%M-%S')
                    filename = (
                        f"{self.data_out}/{str(plane) + '_' + timestamp}.csv")
                    plane_df.write_csv(str(filename))
                    logging.info(
                        f'Saved dataframe for plane {plane} with shape {plane_df.shape} in {filename}'
                        )
            except Exception as e:
                logging.info(traceback.format_exc())
                logging.info(f'Error saving dataframe for plane {plane}: {e}')

    def stop(self):
        try:
            """Finalize the worker by listing saved dataframes."""
            files = glob.glob(os.path.join(self.data_out, '**'), recursive=True
                )
            df_files = [f for f in files if re.search('\\.(csv|parquet)$', f)]
            n_df = len(df_files)
            if self.verbose > 0:
                logging.info(f'{n_df} dataframes')
                for f in df_files:
                    logging.info('\t' + str(Path(f)))
                if not n_df:
                    logging.info('No dataframe created')
        except Exception as err:
            logging.info(f'Error while trying to find dataframes: {err}')
        super().stop()
