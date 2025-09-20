
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('~/agilab/src/agilab/apps/sb3_trainer_project'), install_type=1, verbose=False)
    res = await AGI.get_distrib(app_env, verbose=False,
                               workers=None, path="data/sb3_trainer", save_uri="data/sb3_trainer", args=[{'name': 'PPO', 'args': {'policy': 'MlpPolicy', 'learning_rate': 0.0003, 'gamma': 0.99, 'gae_lambda': 0.95, 'total_timesteps': 850000, 'n_steps': 2048, 'batch_size': 64, 'n_epochs': 10, 'clip_range': 0.2, 'ent_coef': 0.0, 'vf_coef': 0.5, 'max_grad_norm': 0.5, 'normalize_advantage': True, 'use_sde': False, 'sde_sample_freq': -1, 'tensorboard_log': '', 'stats_window_size': 100, 'device': 'auto', 'verbose': 0}}, {'name': 'DQN', 'args': {'policy': 'MlpPolicy', 'learning_rate': 0.0003, 'gamma': 0.99, 'tau': 1.0, 'total_timesteps': 850000, 'buffer_size': 1000000, 'learning_starts': 50000, 'batch_size': 64, 'gradient_steps': 1, 'train_freq': (4, 'step'), 'target_update_interval': 10000, 'max_grad_norm': 0.5, 'optimize_memory_usage': False, 'exploration_fraction': 0.1, 'exploration_initial_eps': 1.0, 'exploration_final_eps': 0.05, 'tensorboard_log': '', 'device': 'auto', 'verbose': 0}}])
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())
            
