"""

    Auteur: Rémy CHEN

"""
import warnings
import os
from typing import Unpack, Literal
import shutil
import getpass
import py7zr
from pydantic import BaseModel, validator, conint, confloat
# from agi_runner import AGI
from agi_node.agi_dispatcher import BaseWorker,WorkDispatcher
from agi_env import AgiEnv
from pathlib import Path
import traceback
warnings.filterwarnings('ignore')
import pandas as pd
import logging
logger = logging.getLogger(__name__)


class LinkSimArgs(BaseModel):
    path: str = '~/data/link_sim'
    data_out: str = '~/data/link_sim/dataframe'
    data_dir: str = '~/data/link_sim/dataset'
    data_flight: str = 'flights'
    data_sat: str = 'sat'
    plane_conf_path: str = ('plane_conf.json',)


def combine_csvs_from_folder(flight_path, sat_path, index_column='time_s'
    ) ->pd.DataFrame:
    """
    Reads all CSV files in a specified folder, stacks them into a single
    Pandas DataFrame, and sets the index to the specified column.

    Args:
        folder_path (str or Path): The path to the folder containing CSV files.
        index_column (str): The name of the column to set as the index.

    Returns:
        pandas.DataFrame: A single DataFrame containing data from all CSVs,
                          with the specified index_column set as the index.
                          Returns an empty DataFrame if no CSVs are found or
                          if an error occurs during processing.
    """
    flight_folder = Path(flight_path)
    if not flight_folder.is_dir():
        print(f"Error: Folder '{flight_path}' not found.")
        return None
    flight_csv_files = list(flight_folder.glob('*.csv'))
    if not flight_csv_files:
        print(f"No CSV files found in '{flight_path}'.")
        return None
    list_of_dfs = []
    successful_reads = 0
    json_label = {}
    max_index = 0
    max_rows = 0
    max_flight_time = 0
    for file_path in flight_csv_files:
        try:
            df = pd.read_csv(file_path)
            if 'worker_id' in df.columns.tolist():
                df.drop('worker_id', axis=1, inplace=True)
            if df.shape[0] > max_rows:
                max_rows = df.shape[0]
            if df.iloc[0]['plane_id'].item() > max_index:
                max_index = df.iloc[0]['plane_id'].item()
            if df.shape[0] > max_flight_time:
                max_flight_time = df.shape[0]
            df['source_file'] = flight_folder / file_path.name
            df['file_name'] = file_path.name
            json_label[df.iloc[0]['plane_id'].item()] = file_path.name.replace(
                '_traj.csv', '')
            list_of_dfs.append(df)
            successful_reads += 1
        except pd.errors.EmptyDataError:
            print(f'Warning: {file_path.name} is empty and will be skipped.')
        except Exception as e:
            print(f'Error reading {file_path.name}: {e}')
    return max_index,max_rows


def analyze_csvs_in_folder(folder_flights_path: str, folder_sat_path: str,
    verbose: bool=False) ->tuple:
    """
    Reads all CSV files in a specified folder, extracts the number of rows,
    and the unique 'plane_id' from each file.

    Args:
        folder_path (str): The path to the folder containing CSV files.
        verbose (bool, optional): If True, prints detailed processing information,
                                  warnings, and errors to stdout. Defaults to False.

    Returns:
        Tuple[WrappedListOfPlaneIdNumRowsTuples, WrappedListOfSinglePlaneIdLists]:
        A tuple containing two lists:
        1.  A list that contains a single inner list of (plane_id, num_rows) tuples.
            Example: `[[(id1, rows1), (id2, rows2), ...]]`
        2.  A list that contains a single inner list, where each element of this
            inner list is itself a list containing a single plane_id.
            Example: `[[[id1], [id2], ...]]`

        If the folder is not found or no CSVs are processed, it returns `([[]], [[]])`.
        'plane_id' will be None if the column is missing, empty, or contains multiple
        unique non-NaN values (with a warning printed if verbose).
        'num_rows' will be None if there was an error reading the file.
    """
    max_index,max_rows = combine_csvs_from_folder(flight_path=folder_flights_path,
        sat_path=folder_sat_path)
    target_folder_flights = folder_flights_path
    target_folder_sat = folder_sat_path
    processed_plane_id_rows_tuples: ListOfPlaneIdNumRowsTuples = []
    processed_single_plane_id_lists: ListOfSinglePlaneIdLists = []
    if not target_folder_flights.is_dir():
        if verbose:
            print(
                f"Error: Folder '{folder_flights_path}' not found or is not a directory."
                )
        return [processed_plane_id_rows_tuples], [
            processed_single_plane_id_lists]
    if not target_folder_sat.is_dir():
        if verbose:
            print(
                f"Error: Folder '{folder_sat_path}' not found or is not a directory."
                )
        return [processed_plane_id_rows_tuples], [
            processed_single_plane_id_lists]
    csv_files_path = (
            [[file, "flight"] for file in target_folder_flights.glob('*.csv')] +
            [[file, "sat"] for file in target_folder_sat.glob('*.csv')]
    )
    for csv_file_path,file_type in csv_files_path:
        filename = csv_file_path.name
        file_info = {'filename': filename, 'num_rows': 0, 'plane_id': None}
        if verbose:
            print(f'Processing {filename}...')
        try:
            df = pd.read_csv(csv_file_path)
            file_info['num_rows'] = len(df)
            if df.empty:
                if verbose:
                    print(f"  - Info: File '{filename}' is empty.")
            elif 'plane_id' not in df.columns:
                if verbose:
                    print(f"  - Warning: 'plane_id' column not found in '{filename}'.")
            else:
                unique_plane_ids = df['plane_id'].dropna().unique(
                    ) if 'sat' not in filename else df['plane_id'].dropna().unique(
                    ) + max_index + 1
                if len(unique_plane_ids) == 0:
                    if verbose:
                        print(f"  - Warning: 'plane_id' column in '{filename}' contains no valid (non-NaN) values.")
                elif len(unique_plane_ids) == 1:
                    val = unique_plane_ids[0]
                    file_info['plane_id'] = val.item() if hasattr(val, 'item'
                        ) else val
                else:
                    if verbose:
                        print(
                            f"  - Warning: Multiple unique 'plane_id' values found in '{filename}': {list(unique_plane_ids)}."
                            )
                        print(
                            f'             Using the first one: {unique_plane_ids[0]}.'
                            )
                    val = unique_plane_ids[0]
                    file_info['plane_id'] = val.item() if hasattr(val, 'item'
                        ) else val
        except pd.errors.EmptyDataError:
            if verbose:
                print(
                    f"  - Warning: File '{filename}' is empty and could not be parsed by pandas."
                    )
        except Exception as e:
            if verbose:
                print(f"  - Error processing file '{filename}': {e}")
            file_info['num_rows'] = None
            file_info['plane_id'] = None
        if file_type != "sat":
            processed_plane_id_rows_tuples.append((file_info['plane_id'],
                                                   file_info['num_rows']))
        else:
            processed_plane_id_rows_tuples.append((file_info['plane_id'],
                                                   max_rows))
        processed_single_plane_id_lists.append([file_info['plane_id']])
    return processed_plane_id_rows_tuples, [processed_single_plane_id_lists]


class LinkSim(BaseWorker):

    def __init__(self, env, **args: Unpack[LinkSimArgs]):
        self.args = args
        self.path = '~/data/link_sim'
        self.data_out = args['data_out'
            ] if 'data_out' in args else '~/data/link_sim/dataset'
        self.data_dir = args['data_dir'
            ] if 'data_dir' in args else '~/data/link_sim/dataset'
        self.data_flight = args['data_flight'
            ] if 'data_flight' in args else 'data/flights'
        self.data_sat = args['data_sat'] if 'data_sat' in args else 'data/sat'
        self.plane_conf_path = args['plane_conf_path'
            ] if 'plane_conf' in args else 'plane_conf.json'
        """
        remove dataframe files from previous run
        """
        try:
            if os.path.exists(self.data_out):
                shutil.rmtree(self.data_out, ignore_errors=False, onerror=
                    BaseWorker.onerror)
            os.makedirs(self.data_out, exist_ok=True)
        except Exception as e:
            print(f'warning issue while trying to remove directory: {e}')
        pass

    def build_distribution(self,workers):
        """build distribution"""
        try:
            workers_chunks, workers_planes_dist = analyze_csvs_in_folder(
                Path(self.data_dir).expanduser() / self.data_flight, Path(
                self.data_dir).expanduser() / self.data_sat, verbose=False)
            workers_chunks = WorkDispatcher.make_chunks(
                len(workers_chunks),workers_chunks, verbose=self.verbose, workers=workers, threshold=12
            )
            workers_link_dist = []
            for worker in workers_chunks:
                worker_list = []
                for chunk in worker:
                    worker_list.append([chunk[0]])
                workers_link_dist.append(worker_list)
        except Exception as e:
            print(traceback.format_exc())
            print(f'warning issue while trying to build distribution: {e}')
        return workers_link_dist, workers_chunks, 'plane', 'files', 'ko'
