import os
import re
import traceback
from pydantic import BaseModel, validator, conint, confloat
import shutil
import warnings
from pathlib import Path
from typing import Unpack, Literal
import py7zr
import polars as pl
from datetime import date
import json
import math
# from agi_runner import AGI
from agi_node.agi_dispatcher import BaseWorker,WorkDispatcher
from agi_env import AgiEnv
warnings.filterwarnings('ignore')
import logging
logger = logging.getLogger(__name__)


class FlightTrajectoryArgs(BaseModel):
    """FlightTrajectoryArgs contains Arguments for FlightTrajectory"""
    path: str = '~/data/flight_trajectory'
    flight_id: int = 1
    data_out: str = '~/data/flight_trajectory/dataframe'
    data_dir: str = '~/data/flight_trajectory/dataset'
    beam_file: str = 'beams.csv'
    sat_file: str = 'satellites.csv'
    waypoints: str = 'waypoints.geojson'


class FlightTrajectory(BaseWorker):
    """FlightTrajectory class provides methods to orchester the run"""
    ivq_logs = None

    def __init__(self, env, **args: Unpack[FlightTrajectoryArgs]):
        """
        Initialize a FlightTrajectory object with provided arguments.

        Args:
            **args (Unpack[FlightTrajectoryArgs]): Keyword arguments to configure the FlightTrajectory object.
                Possible arguments include:
                    - data_source (str): Source of the data, either 'file' or 'hawk'.
                    - files (str): Path pattern or file name.
                    - path (str): Path to store data files.
                      remark: There is also src/flight_trajectory_worker/dataset.7z for dataset replication per worker
                    - nfile (int): Maximum number of files to process.
                    - datemin (str): Minimum date for data processing.
                    - datemax (str): Maximum date for data processing.
                    - output_format (str): Output format for processed data, either 'parquet' or 'csv'.

        Raises:
            ValueError: If an invalid input mode is provided for data_source.
        """
        self.args = args
        self.path = args['path'] if 'path' in args else '~/data/flight_trajectory'
        self.data_out = args['data_out'
            ] if 'data_out' in args else '~/data/flight_trajectory/dataframe'
        self.data_dir = args['data_dir'
            ] if 'data_dir' in args else '~/data/flight_trajectory/dataset'
        # self.beam_file = args['beam_file'
        #     ] if 'beam_file' in args else 'beams.csv'
        # self.sat_file = args['sat_file'
        #     ] if 'sat_file' in args else 'satellites.csv'
        self.waypoints = args['waypoints'
            ] if 'waypoints' in args else 'waypoints.geojson'
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
        return

    def haversine(self, lon1, lat1, lon2, lat2):
        """
        Calculate the great-circle distance between two points
        on the Earth specified by longitude and latitude.
        Returns distance in kilometers.
        """
        lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2
            ) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        R = 6371.0
        return R * c

    def build_distribution(self,workers):
        """build_distrib: to provide the list of files per planes (level1) and per workers (level2)
        the level 1 has been think to prevent that à job that requires all the output-data of a plane have to wait for another
        my_code_worker which would have collapse the overall performance

        Args:

        Returns:

        """
        try:
            data_dir_path = Path(self.data_dir)
            expanded_data_dir_path = data_dir_path.expanduser()
            full_waypoints_path = expanded_data_dir_path / self.waypoints
            with open(full_waypoints_path, 'r') as file:
                list_waypoints = json.load(file)
            full_data = []
            for i in range(len(list_waypoints['features'])):
                data = list_waypoints['features'][i]['geometry']['coordinates'
                    ][0] if isinstance(list_waypoints['features'][i][
                    'geometry']['coordinates'][0][0], list
                    ) else list_waypoints['features'][i]['geometry'][
                    'coordinates']
                full_data.append(data)
            workers_chunks, workers_planes_dist = [], [[]]
            for idx, sequence in enumerate(full_data):
                total_length = 0.0
                for (lon1, lat1), (lon2, lat2) in zip(sequence, sequence[1:]):
                    total_length += self.haversine(lon1, lat1, lon2, lat2)
                workers_chunks.append((idx, total_length))
                workers_planes_dist[0].append([idx])

            workers_chunks = WorkDispatcher.make_chunks(
                len(workers_chunks), workers_chunks, verbose=self.verbose, workers=workers, threshold=12
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
        return workers_planes_dist, workers_chunks, 'plane', 'files', 'ko'
