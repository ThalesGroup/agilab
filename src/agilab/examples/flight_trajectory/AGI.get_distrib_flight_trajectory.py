
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('~/agilab/src/agilab/apps/flight_trajectory_project'), install_type=1, verbose=True)
    res = await AGI.get_distrib(app_env,
                                #scheduler="127.0.0.1", workers={"127.0.0.1":2},
                                path="data/flight_trajectory", num_flights=1, data_out="data/flight_trajectory/dataframe", data_uri="data/flight_trajectory/dataset", beam_file="beams.csv", sat_file="satellites.csv", waypoints="waypoints.geojson", yaw_angular_speed=1.0, roll_angular_speed=3.0, pitch_angular_speed=2.0, vehicule_acceleration=5.0, max_speed=900.0, max_roll=30.0, max_pitch=12.0, target_climbup_pitch=8.0, pitch_enable_speed_ratio=0.3, altitude_loss_speed_treshold=400.0, landing_speed_target=200.0, descent_pitch_target=-3.0, landing_pitch_target=3.0, cruising_pitch_max=3.0, descent_alt_treshold_landing=500, max_speed_ratio_while_turining=0.8, enable_climb=False, enable_descent=False, default_alt_value=4000.0, plane_type="avions")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())
