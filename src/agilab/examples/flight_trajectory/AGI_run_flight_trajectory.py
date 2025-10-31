
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "/Users/jpm/PycharmProjects/agilab/src/agilab/apps"
APP = "flight_trajectory_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.run(app_env, 
                        mode=15, 
                        scheduler="127.0.0.1", 
                        workers={'127.0.0.1': 2}, 
                        num_flights=20, data_uri="/Users/jpm/data/flight_trajectory/dataset", data_source="file", beam_file="beams.csv", sat_file="satellites.csv", waypoints="waypoints.geojson", yaw_angular_speed=1.0, roll_angular_speed=3.0, pitch_angular_speed=2.0, vehicule_acceleration=5.0, max_speed=900.0, max_roll=30.0, max_pitch=12.0, target_climbup_pitch=8.0, pitch_enable_speed_ratio=0.3, altitude_loss_speed_treshold=400.0, landing_speed_target=200.0, descent_pitch_target=-3.0, landing_pitch_target=3.0, cruising_pitch_max=3.0, descent_alt_treshold_landing=500, max_speed_ratio_while_turining=0.8, enable_climb=False, enable_descent=False, default_alt_value=4000.0, plane_type="avions", dataset_format="csv")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())