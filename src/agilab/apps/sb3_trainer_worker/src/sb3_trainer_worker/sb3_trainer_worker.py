"""
Module sb3_trainer_worker extension of your_code


    Auteur: yourself

"""
import json
import os
import traceback
import warnings
import logging
from pathlib import Path
from types import SimpleNamespace
from agi_env import AgiEnv, normalize_path
from agi_node.dag_worker import DagWorker
from sklearn.utils._repr_html import params
from stable_baselines3 import DQN,PPO
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.evaluation import evaluate_policy
from stable_baselines3.common.env_util import make_vec_env
import gymnasium as gym
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.tensorboard import SummaryWriter
import time
from sb3_trainer_worker.envs.time_routing_env import TimeRoutingEnv
# Optional ILP solver; fall back to lightweight stubs if ilp_worker is missing.
import networkx as nx
try:
    from ilp_worker.demand import Demand
    from ilp_worker.flyenv import Flyenv
    from ilp_worker.milp import MILP
except Exception:  # pragma: no cover - fallback when ilp_worker not installed
    class Demand:
        def __init__(self, source, destination, bw, priority=1, max_packet_loss=10, max_latency=750):
            self.source = source
            self.destination = destination
            self.bw = bw
            self.priority = priority
            self.max_packet_loss = max_packet_loss
            self.max_latency = max_latency
            self.service = None

    class _Alloc:
        def __init__(self, demand, delivered_bandwidth, path, latency):
            self.demand = demand
            self.delivered_bandwidth = delivered_bandwidth
            self.routed = True
            self.path = path
            self.latency = latency

    class Flyenv:
        def __init__(self, *_, **__):
            self.graph = None

        def generate_environment_from_graph(self, graph, _):
            self.graph = graph

    class MILP:
        def __init__(self, *_args, **_kwargs):
            pass

        def solve(self, demands):
            allocations = []
            for d in demands:
                allocations.append(_Alloc(d, d.bw, [d.source, d.destination], 0.0))
            return allocations
import torch
import torch.nn as nn

# Lightweight message-passing network for graph routing without torch_geometric.
class GraphAllocNet(nn.Module):
    def __init__(self, node_feat_dim: int, edge_feat_dim: int, demand_feat_dim: int, hidden: int = 64, layers: int = 2):
        super().__init__()
        self.node_encoder = nn.Sequential(nn.Linear(node_feat_dim, hidden), nn.ReLU())
        self.edge_encoder = nn.Sequential(nn.Linear(edge_feat_dim, hidden), nn.ReLU())
        self.layers = nn.ModuleList(
            [
                nn.ModuleDict(
                    {
                        "msg": nn.Sequential(nn.Linear(hidden * 2 + hidden, hidden), nn.ReLU()),
                        "upd": nn.Sequential(nn.Linear(hidden + hidden, hidden), nn.ReLU()),
                    }
                )
                for _ in range(max(1, layers))
            ]
        )
        self.readout = nn.Sequential(
            nn.Linear(hidden * 2 + demand_feat_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, 1),
        )

    def forward(
        self,
        node_feats: torch.Tensor,
        edge_index: torch.Tensor,
        edge_feats: torch.Tensor,
        demand_pairs: torch.Tensor,
        demand_feats: torch.Tensor,
    ) -> torch.Tensor:
        h_nodes = self.node_encoder(node_feats)
        h_edges = self.edge_encoder(edge_feats)

        for layer in self.layers:
            src, dst = edge_index
            messages = layer["msg"](torch.cat([h_nodes[src], h_edges, h_nodes[dst]], dim=-1))
            agg = torch.zeros_like(h_nodes)
            agg.index_add_(0, dst, messages)
            h_nodes = layer["upd"](torch.cat([h_nodes, agg], dim=-1))

        src = demand_pairs[:, 0]
        dst = demand_pairs[:, 1]
        demand_stack = torch.cat([h_nodes[src], h_nodes[dst], demand_feats], dim=-1)
        alloc = torch.sigmoid(self.readout(demand_stack)).squeeze(-1)
        return alloc
### fix the MP issues because of the vectorization of the env
# import sys, pathlib
# sys.path = [str(p) if isinstance(p, pathlib.Path) else p for p in sys.path]



logger = logging.getLogger(__name__)
warnings.filterwarnings('ignore')


class _MutableNamespace(SimpleNamespace):
    """SimpleNamespace that also supports item-style access."""

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)
def create_incremented_folder(base_path: Path, name: str,return_name = False) -> Path:
    """
    Create a folder inside base_path named 'name_<number>' where <number> is the
    next available integer. Returns the full path of the created folder.

    Parameters
    ----------
    base_path : Path
        The directory in which to create the new folder.
    name : str
        The base name for the folder (without number suffix).

    Returns
    -------
    Path
        Full path to the newly created folder.
    """
    # Ensure the base directory exists
    base_path.mkdir(parents=True, exist_ok=True)

    # Find the next available number
    number = 1
    while (base_path / f"{name}_{number}").exists():
        number += 1

    # Create the new folder
    new_folder = base_path / f"{name}_{number}"
    new_folder.mkdir()
    if return_name:
        return new_folder,f"{name}_{number}"
    else:
        return new_folder
def build_ppo(env,tensorboard_path, params: dict | None = None) -> PPO:
    """
    Build an SB3 PPO model from a (possibly sparse) params dict.
    Any None/missing fields fall back to SB3-like defaults.
    """
    # SB3-ish defaults (useful if some keys are absent)
    defaults = {
        "policy": "MlpPolicy",
        "learning_rate": 3e-4,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "n_steps": 2048,
        "batch_size": 64,
        "n_epochs": 10,
        "clip_range": 0.2,
        "ent_coef": 0.0,
        "vf_coef": 0.5,
        "max_grad_norm": 0.5,
        "normalize_advantage": True,
        "clip_range_vf": None,
        "target_kl": None,
        "use_sde": False,
        "sde_sample_freq": -1,
        "tensorboard_log": None,
        "stats_window_size": 100,
        "device": "auto",
        "verbose": 0,
        "policy_kwargs": None,
        "seed": None,
    }

    cfg = {**defaults, **(params or {})}
    if "total_timesteps" in cfg:
        del cfg["total_timesteps"]
    # Normalize a few user-provided oddities
    if cfg.get("tensorboard_log") in ("",None):
        cfg["tensorboard_log"] = tensorboard_path

    if cfg.get("tensorboard_log") is not None:
        cfg["tensorboard_log"] = Path(cfg["tensorboard_log"]).expanduser()

    # Strip keys with value None (SB3 treats omitted better than explicit None)
    cfg = {k: v for k, v in cfg.items() if v is not None}

    # policy must be a separate positional/kwarg; env is required
    policy = cfg.pop("policy", "MlpPolicy")

    return PPO(policy=policy, env=env, **cfg)
def build_dqn(env, tensorboard_path, params: dict | None = None) -> DQN:
    """
    Build an SB3 DQN model from a (possibly sparse) params dict.
    - Fills sensible defaults for missing fields.
    - Converts JSON-style train_freq like [4, "step"] to SB3 tuple.
    - Injects tensorboard_path when param is "" or None.
    - Strips None values and keys not accepted by DQN/BaseAlgorithm.
    """
    # SB3-ish defaults (see docs)
    defaults = {
        "policy": "MlpPolicy",
        "learning_rate": 1e-4,
        "gamma": 0.99,
        "tau": 1.0,                     # Polyak factor (1.0 = hard update)
        "buffer_size": 100_000,
        "learning_starts": 1_000,
        "batch_size": 32,
        "train_freq": 4,                # int or (int, "step"/"episode")
        "gradient_steps": 1,
        "target_update_interval": 10_000,
        "max_grad_norm": 10.0,
        "optimize_memory_usage": False,
        "exploration_fraction": 0.1,
        "exploration_initial_eps": 1.0,
        "exploration_final_eps": 0.05,
        "tensorboard_log": None,
        "stats_window_size": 100,
        "device": "auto",
        "verbose": 0,
        "policy_kwargs": None,
        "seed": None,
    }

    # Only keep keys actually accepted by DQN/BaseAlgorithm
    allowed = {
        "policy", "learning_rate", "gamma", "tau",
        "buffer_size", "learning_starts", "batch_size",
        "train_freq", "gradient_steps", "target_update_interval",
        "max_grad_norm", "optimize_memory_usage",
        "exploration_fraction", "exploration_initial_eps", "exploration_final_eps",
        "tensorboard_log", "stats_window_size",
        "device", "verbose", "policy_kwargs", "seed",
    }

    raw = params or {}
    cfg = {**defaults, **{k: v for k, v in raw.items() if k in allowed}}

    # Drop keys that belong to .learn() or elsewhere (defensive)
    for k in ("total_timesteps",):
        cfg.pop(k, None)

    # TensorBoard path handling (like your PPO helper)
    if cfg.get("tensorboard_log") in ("", None):
        cfg["tensorboard_log"] = tensorboard_path
    if cfg.get("tensorboard_log") is not None:
        cfg["tensorboard_log"] = Path(cfg["tensorboard_log"]).expanduser()

    # Convert train_freq from JSON array [n, "step"/"episode"] to tuple
    tf = cfg.get("train_freq")
    if isinstance(tf, (list, tuple)) and len(tf) == 2:
        cfg["train_freq"] = (tf[0], tf[1])

    # Strip None values (SB3 prefers omission)
    cfg = {k: v for k, v in cfg.items() if v is not None}

    policy = cfg.pop("policy", "MlpPolicy")
    return DQN(policy=policy, env=env, **cfg)
def evaluate_model(model, n_eval_episodes=10):
    """
    Evaluates the model using a given environment.

    Args:
        model: The trained model to evaluate.
        env: The environment in which the model will be evaluated.
        n_eval_episodes (int): Number of episodes for evaluation.

    Returns:
        float: The mean reward across the evaluation episodes.
        float: The standard deviation of the reward.
    """
    env = make_vec_env("LunarLander-v3", n_envs=8, seed=0)
    mean_reward, std_reward = evaluate_policy(model, env, n_eval_episodes=n_eval_episodes)
    return mean_reward,
def evaluate_model_torch(model, n_eval_episodes=30):
    """
    Evaluates the model using a given environment.

    NOTE: 'model' here is a file path to a saved .pt checkpoint from our custom PPO.

    Returns:
        float: The mean reward across the evaluation episodes.
        float: The standard deviation of the reward.
        str:   The model identifier (here: path string).
    """

    # Load checkpoint
    try:
        checkpoint = torch.load(model, map_location="cpu", weights_only=False)
    except TypeError:
        # for older torch<2.6 where weights_only doesn't exist
        checkpoint = torch.load(model, map_location="cpu")

    obs_dim = checkpoint["obs_dim"]
    act_dim = checkpoint["act_dim"]

    class PolicyOnly(torch.nn.Module):
        def __init__(self, obs_dim, act_dim):
            super().__init__()
            hidden = 64
            self.policy = torch.nn.Sequential(
                torch.nn.Linear(obs_dim, hidden), torch.nn.Tanh(),
                torch.nn.Linear(hidden, hidden), torch.nn.Tanh(),
                torch.nn.Linear(hidden, act_dim)
            )

        def act_greedy(self, x):
            logits = self.policy(x)
            probs = torch.distributions.Categorical(logits=logits)
            return torch.argmax(probs.probs, dim=-1)

    policy = PolicyOnly(obs_dim, act_dim)
    # Load only policy.* keys (ignore value.*)
    state_dict = {k: v for k, v in checkpoint["state_dict"].items() if k.startswith("policy.")}
    policy.load_state_dict(state_dict, strict=False)
    policy.eval()

    env = gym.make("LunarLander-v3")
    rewards = []
    for _ in range(n_eval_episodes):
        obs, _ = env.reset()
        done = False
        ep_rew = 0.0
        while not done:
            with torch.no_grad():
                a = policy.act_greedy(torch.tensor(obs, dtype=torch.float32).unsqueeze(0))
            a = int(a.item())
            obs, r, term, trunc, _ = env.step(a)
            ep_rew += r
            done = term or trunc
        rewards.append(ep_rew)

    mean_reward = float(np.mean(rewards))
    std_reward = float(np.std(rewards))
    return mean_reward, std_reward
def train_manual_PPO(learning_rate, total_timesteps, path_save, tensorboard_folder):
    """
    Train PPO (manual implementation) on LunarLander-v3 with rich TensorBoard logging.

    Args:
        learning_rate (float): Adam learning rate.
        total_timesteps (int): Total env timesteps to collect (like SB3).
        path_save (Path or str): Folder path to save the final model.
        tensorboard_folder (Path or str): Base folder for TensorBoard runs.
    Returns:
        Path to saved model.
    """
    # --- Setup paths & writer ---
    path_save = Path(path_save)
    path_save.mkdir(parents=True, exist_ok=True)
    tensorboard_folder = Path(tensorboard_folder)
    tensorboard_folder.mkdir(parents=True, exist_ok=True)

    run_name = f"ppo_manual_LunarLander_lr{learning_rate:g}_{int(time.time())}"
    writer = SummaryWriter(log_dir=tensorboard_folder / run_name)

    # --- Device ---
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # --- Hyperparameters (SB3-like) ---
    n_envs = 5
    rollout_steps_total = 2048           # steps per update across all envs
    steps_per_env = rollout_steps_total // n_envs
    n_epochs = 10
    batch_size = 64
    gamma = 0.99
    gae_lambda = 0.95
    clip_range = 0.2
    ent_coef = 0.01
    vf_coef = 0.5
    max_grad_norm = 0.5

    # --- Vectorized env (no SB3) ---
    def _make_env(seed):
        def _thunk():
            env = gym.make("LunarLander-v3")
            env.reset(seed=seed)
            return env
        return _thunk

    env = gym.vector.AsyncVectorEnv([_make_env(seed=i) for i in range(n_envs)])
    obs, _ = env.reset(seed=0)

    obs_dim = obs.shape[-1]
    n_actions = env.single_action_space.n

    # --- Actor-Critic ---
    class ActorCritic(nn.Module):
        def __init__(self, obs_dim, act_dim, hidden=64):
            super().__init__()
            self.policy = nn.Sequential(
                nn.Linear(obs_dim, hidden), nn.Tanh(),
                nn.Linear(hidden, hidden), nn.Tanh(),
                nn.Linear(hidden, act_dim)
            )
            self.value = nn.Sequential(
                nn.Linear(obs_dim, hidden), nn.Tanh(),
                nn.Linear(hidden, hidden), nn.Tanh(),
                nn.Linear(hidden, 1)
            )

        def forward(self, x):
            logits = self.policy(x)
            value = self.value(x).squeeze(-1)
            return logits, value

        def act(self, x):
            logits, value = self.forward(x)
            probs = torch.distributions.Categorical(logits=logits)
            action = probs.sample()
            logprob = probs.log_prob(action)
            return action, logprob, value

        def evaluate_actions(self, x, actions):
            logits, value = self.forward(x)
            probs = torch.distributions.Categorical(logits=logits)
            logprob = probs.log_prob(actions)
            entropy = probs.entropy()
            return logprob, entropy, value

    net = ActorCritic(obs_dim, n_actions).to(device)
    optimizer = optim.Adam(net.parameters(), lr=learning_rate)

    # (Optional) add graph once
    try:
        example = torch.zeros((n_envs, obs_dim), dtype=torch.float32).to(device)
        writer.add_graph(net, example)
    except Exception:
        pass  # Graph is nice-to-have, not required

    # --- Episode tracking across vector envs ---
    running_return = np.zeros(n_envs, dtype=np.float32)
    running_length = np.zeros(n_envs, dtype=np.int32)
    completed_returns = []
    completed_lengths = []

    # --- Utils ---
    def explained_variance(y_true_np, y_pred_np):
        var_y = np.var(y_true_np)
        return np.nan if var_y == 0 else 1.0 - np.var(y_true_np - y_pred_np) / (var_y + 1e-8)

    # --- Rollout collection with GAE ---
    def collect_rollout():
        nonlocal obs, running_return, running_length, completed_returns, completed_lengths

        obs_buf = np.zeros((steps_per_env, n_envs, obs_dim), dtype=np.float32)
        actions_buf = np.zeros((steps_per_env, n_envs), dtype=np.int64)
        logprobs_buf = np.zeros((steps_per_env, n_envs), dtype=np.float32)
        rewards_buf = np.zeros((steps_per_env, n_envs), dtype=np.float32)
        dones_buf = np.zeros((steps_per_env, n_envs), dtype=np.bool_)
        values_buf = np.zeros((steps_per_env, n_envs), dtype=np.float32)

        for t in range(steps_per_env):
            obs_tensor = torch.tensor(obs, dtype=torch.float32, device=device)
            with torch.no_grad():
                action, logprob, value = net.act(obs_tensor)
            action_np = action.detach().cpu().numpy()

            next_obs, reward, terminated, truncated, _ = env.step(action_np)
            done = np.logical_or(terminated, truncated)

            # buffers
            obs_buf[t] = obs
            actions_buf[t] = action_np
            logprobs_buf[t] = logprob.detach().cpu().numpy()
            rewards_buf[t] = reward
            dones_buf[t] = done
            values_buf[t] = value.detach().cpu().numpy()

            # episode accounting
            running_return += reward.astype(np.float32)
            running_length += 1
            for i in range(n_envs):
                if done[i]:
                    completed_returns.append(float(running_return[i]))
                    completed_lengths.append(int(running_length[i]))
                    running_return[i] = 0.0
                    running_length[i] = 0

            obs = next_obs

        with torch.no_grad():
            next_obs_tensor = torch.tensor(obs, dtype=torch.float32, device=device)
            _, next_value = net.forward(next_obs_tensor)
            next_value = next_value.detach().cpu().numpy()

        # GAE
        advantages = np.zeros_like(rewards_buf, dtype=np.float32)
        lastgaelam = np.zeros((n_envs,), dtype=np.float32)
        for t in reversed(range(steps_per_env)):
            next_nonterminal = 1.0 - dones_buf[t].astype(np.float32)
            next_values = next_value if t == steps_per_env - 1 else values_buf[t + 1]
            delta = rewards_buf[t] + gamma * next_values * next_nonterminal - values_buf[t]
            lastgaelam = delta + gamma * gae_lambda * next_nonterminal * lastgaelam
            advantages[t] = lastgaelam

        returns = advantages + values_buf

        def flat(x):
            return x.reshape(-1, *x.shape[2:]) if x.ndim > 2 else x.reshape(-1)

        batch = {
            "obs": flat(obs_buf),
            "actions": flat(actions_buf),
            "logprobs": flat(logprobs_buf),
            "advantages": flat(advantages),
            "returns": flat(returns),
            "values": flat(values_buf),
            "dones": dones_buf.reshape(-1),
            "rewards": rewards_buf.reshape(-1),
        }
        # Rollout-level quick stats for logging
        rollout_stats = {
            "adv_mean": float(np.mean(batch["advantages"])),
            "adv_std": float(np.std(batch["advantages"])),
            "ret_mean": float(np.mean(batch["returns"])),
            "ret_std": float(np.std(batch["returns"])),
        }
        return batch, rollout_stats

    # --- Training loop ---
    num_updates = int(total_timesteps // (n_envs * steps_per_env))
    global_step = 0
    start_time = time.time()

    for update in range(1, num_updates + 1):
        update_start = time.time()
        batch, rollout_stats = collect_rollout()
        global_step += n_envs * steps_per_env

        # Normalize advantages
        adv = batch["advantages"]
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        batch["advantages"] = adv

        # Tensors
        obs_t = torch.tensor(batch["obs"], dtype=torch.float32, device=device)
        act_t = torch.tensor(batch["actions"], dtype=torch.long, device=device)
        old_logp_t = torch.tensor(batch["logprobs"], dtype=torch.float32, device=device)
        ret_t = torch.tensor(batch["returns"], dtype=torch.float32, device=device)
        val_t = torch.tensor(batch["values"], dtype=torch.float32, device=device)

        n_samples = obs_t.shape[0]
        idxs = np.arange(n_samples)

        # Track diagnostics aggregated over epochs/minibatches
        policy_losses, value_losses, entropies, losses = [], [], [], []
        approx_kls, clip_fracs, grad_norms = [], [], []

        for epoch in range(n_epochs):
            np.random.shuffle(idxs)
            for start_i in range(0, n_samples, batch_size):
                mb = idxs[start_i:start_i + batch_size]
                mb_obs = obs_t[mb]
                mb_act = act_t[mb]
                mb_old_logp = old_logp_t[mb]
                mb_ret = ret_t[mb]
                mb_adv = torch.tensor(adv[mb], dtype=torch.float32, device=device)
                mb_val_old = val_t[mb]

                new_logp, entropy, new_value = net.evaluate_actions(mb_obs, mb_act)

                ratio = (new_logp - mb_old_logp).exp()
                pg_loss1 = -mb_adv * ratio
                pg_loss2 = -mb_adv * torch.clamp(ratio, 1 - clip_range, 1 + clip_range)
                pg_loss = torch.max(pg_loss1, pg_loss2).mean()

                v_pred = new_value
                v_pred_clipped = mb_val_old + (new_value - mb_val_old).clamp(-clip_range, clip_range)
                vf_loss1 = (v_pred - mb_ret).pow(2)
                vf_loss2 = (v_pred_clipped - mb_ret).pow(2)
                vf_loss = 0.5 * torch.max(vf_loss1, vf_loss2).mean()

                entropy_loss = -entropy.mean()
                loss = pg_loss + vf_coef * vf_loss + ent_coef * entropy_loss

                optimizer.zero_grad()
                loss.backward()
                grad_norm = nn.utils.clip_grad_norm_(net.parameters(), max_grad_norm)
                optimizer.step()

                # Diagnostics
                with torch.no_grad():
                    approx_kl = (mb_old_logp - new_logp).mean().abs().item()
                    clip_frac = ((ratio - 1.0).abs() > clip_range).float().mean().item()

                policy_losses.append(pg_loss.item())
                value_losses.append(vf_loss.item())
                entropies.append(entropy.mean().item())
                losses.append(loss.item())
                approx_kls.append(approx_kl)
                clip_fracs.append(clip_frac)
                grad_norms.append(float(grad_norm))

        # Explained variance (using pre-update baseline values vs returns)
        ev = explained_variance(ret_t.detach().cpu().numpy(), val_t.detach().cpu().numpy())

        # Rollout episodic stats
        ep_rew_mean = float(np.mean(completed_returns)) if len(completed_returns) else np.nan
        ep_len_mean = float(np.mean(completed_lengths)) if len(completed_lengths) else np.nan

        # Timing
        update_time = time.time() - update_start
        total_time = time.time() - start_time
        fps = (n_envs * steps_per_env) / max(update_time, 1e-9)
        ups = 1.0 / max(update_time, 1e-9)

        # --- TensorBoard logging (scalars) ---
        writer.add_scalar("charts/learning_rate", optimizer.param_groups[0]["lr"], global_step)
        writer.add_scalar("time/fps", fps, global_step)
        writer.add_scalar("time/updates_per_sec", ups, global_step)
        writer.add_scalar("time/elapsed_seconds", total_time, global_step)
        writer.add_scalar("rollout/adv_mean", rollout_stats["adv_mean"], global_step)
        writer.add_scalar("rollout/adv_std", rollout_stats["adv_std"], global_step)
        writer.add_scalar("rollout/ret_mean", rollout_stats["ret_mean"], global_step)
        writer.add_scalar("rollout/ret_std", rollout_stats["ret_std"], global_step)
        if not np.isnan(ep_rew_mean):
            writer.add_scalar("rollout/ep_rew_mean", ep_rew_mean, global_step)
        if not np.isnan(ep_len_mean):
            writer.add_scalar("rollout/ep_len_mean", ep_len_mean, global_step)

        writer.add_scalar("train/policy_loss", float(np.mean(policy_losses)), global_step)
        writer.add_scalar("train/value_loss", float(np.mean(value_losses)), global_step)
        writer.add_scalar("train/entropy", float(np.mean(entropies)), global_step)
        writer.add_scalar("train/loss", float(np.mean(losses)), global_step)
        writer.add_scalar("train/approx_kl", float(np.mean(approx_kls)), global_step)
        writer.add_scalar("train/clip_fraction", float(np.mean(clip_fracs)), global_step)
        writer.add_scalar("train/explained_variance", float(ev), global_step)
        writer.add_scalar("train/grad_norm", float(np.mean(grad_norms)), global_step)
        writer.add_scalar("charts/update", update, global_step)
        writer.add_scalar("charts/global_step", global_step, global_step)

        # --- Optional histograms every 10 updates ---
        if update % 10 == 0:
            for name, param in net.named_parameters():
                writer.add_histogram(f"params/{name}", param.detach().cpu().numpy(), global_step)
                if param.grad is not None:
                    writer.add_histogram(f"grads/{name}", param.grad.detach().cpu().numpy(), global_step)

    # --- Save & close ---
    save_path = path_save / "PPO_manual_model.pt"
    torch.save({
        "state_dict": net.state_dict(),
        "obs_dim": obs_dim,
        "act_dim": n_actions,
        "arch": "mlp64x2"
    }, save_path)

    writer.close()
    return save_path

class Sb3TrainerWorker(DagWorker):
    """class derived from DagWorker"""

    def start(self):
        """
        Start the function.

        This function prints the file name if the 'verbose' attribute is greater than 0.

        Args:
            self: The current instance of the class.

        Returns:
            None
        """
        logging.info(f'from: {__file__}')
        if self._mode & 2 and 'cy' not in __file__:
            raise RuntimeError('Cython requested but not executed')
        # dispatcher may hand us a SimpleNamespace; convert so existing subscript usages keep working
        if isinstance(getattr(self, "args", None), SimpleNamespace):
            self.args = dict(vars(self.args))
        if isinstance(self.args, dict):
            if "data_in" not in self.args and "path" in self.args:
                self.args["data_in"] = self.args["path"]
            if "data_out" not in self.args and "save_uri" in self.args:
                self.args["data_out"] = self.args["save_uri"]
            if "path" not in self.args and "data_in" in self.args:
                self.args["path"] = self.args["data_in"]
            if "save_uri" not in self.args and "data_out" in self.args:
                self.args["save_uri"] = self.args["data_out"]

    def _output_root(self) -> Path:
        target = None
        if isinstance(getattr(self, "args", None), dict):
            target = self.args.get("data_out") or self.args.get("save_uri")
        if not target:
            target = "sb3_trainer"
        path = Path(target).expanduser()
        if not path.is_absolute():
            env = getattr(self, "env", None)
            share = getattr(env, "agi_share_dir", None)
            if share:
                path = Path(share).expanduser() / path
        return path

    def get_work(self, work: str, args, prev_result):
        """
        :param work: contain the worker function name called by BaseWorker.do_work
        this is type string and not type function to avoid manager (e.g. Sb3Trainer) to be dependant of MyCodeWorker
        :return:
        """
        method = getattr(self, work, None)
        if method is None:
            raise AttributeError(
                f"No such method '{work}' on {self.__class__.__name__}")
        return method(args, prev_result)

    def trainer_DQN(self, args, prev_result):
        try:
            if isinstance(args, SimpleNamespace):
                args = dict(vars(args))
            DQN_folder = self._output_root()/"trainer_DQN"
            os.makedirs(DQN_folder, exist_ok=True)
            os.makedirs(DQN_folder/"tensorboard", exist_ok=True)
            logging.info(f"creating the folder '{DQN_folder}'")
            path = create_incremented_folder(DQN_folder, "DQN_model")
            logging.info(f"Init the environment")
            env = make_vec_env("LunarLander-v3", n_envs=8, seed=0)
            logging.info(f"Init the model")
            model = build_dqn(env, DQN_folder / "tensorboard", args)
            logging.info(f"Launching the learning of the model")
            model.learn(total_timesteps=args["total_timesteps"], tb_log_name=f"DQN")
            logging.info(f"Save the model in '{path}'")
            model.save(path / "DQN_model")
            mean_reward = evaluate_model(model)
            args["mean_reward"] = mean_reward[0]
            json.dump(args, open(path / "DQN_args.json", "w"))
            return args

        except Exception as e:
            logging.error(f'Exception during trainer DQN: {e}')
            traceback.print_exc()

    def trainer_PPO(self, args, prev_result):
        try:
            if isinstance(args, SimpleNamespace):
                args = dict(vars(args))
            PPO_folder = self._output_root()/"trainer_PPO"
            os.makedirs(PPO_folder,exist_ok=True)
            os.makedirs(PPO_folder/"tensorboard",exist_ok=True)
            logging.info(f"creating the folder '{PPO_folder}'")
            path = create_incremented_folder(PPO_folder,"PPO_model")
            # envs = [make_env(seed=i) for i in range(8)]
            # env = SubprocVecEnv(envs)
            logging.info(f"Init the environment")
            env = make_vec_env("LunarLander-v3", n_envs=8, seed=0)
            logging.info(f"Init the model")
            model = build_ppo(env,PPO_folder/"tensorboard",args)
            logging.info(f"Launching the learning of the model")
            model.learn(total_timesteps=args["total_timesteps"], tb_log_name=f"PPO")
            logging.info(f"Save the model in '{path}'")
            model.save(path/"PPO_model")
            mean_reward = evaluate_model(model)
            args["mean_reward"] = mean_reward[0]
            json.dump(args, open(path/"PPO_args.json","w"))
            return args
        except Exception as e:
            logging.error(f'SB3Trainer.trainer_PPO error: {e}')
            traceback.print_exc()

    def trainer_ilp_stepper(self, args, prev_result):
        """Run ILP solver at each timestep using static topology/demands; log per-step allocations."""
        try:
            if isinstance(args, SimpleNamespace):
                args = dict(vars(args))

            time_horizon = int(args.get("time_horizon", 16))
            data_in = Path(args.get("data_in", "network_sim/dataframe")).expanduser()
            if not data_in.is_absolute():
                env = getattr(self, "env", None)
                share = getattr(env, "agi_share_dir", None)
                if share:
                    data_in = Path(share).expanduser() / data_in
            data_out = self._output_root() / "trainer_ilp_stepper"
            data_out.mkdir(parents=True, exist_ok=True)

            topo_path = args.get("topology_path") or data_in / "ilp_topology.gml"
            demands_path = args.get("demands_path") or data_in / "ilp_demands.json"
            trajectories_glob = args.get("trajectories_glob", "flight_trajectory/dataframe/flight_simulation/*.parquet")
            sat_glob = args.get("sat_trajectories_glob", "sat_trajectory/dataframe/flight_simulation/*.parquet")

            base_graph = nx.read_gml(topo_path)
            if not isinstance(base_graph, nx.MultiDiGraph):
                base_graph = nx.MultiDiGraph(base_graph)
            base_graph = nx.convert_node_labels_to_integers(base_graph, label_attribute="label")

            # Load demands
            demands: list[Demand] = []
            try:
                payload = json.loads(Path(demands_path).read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(f"Failed to load demands from {demands_path}: {exc}") from exc
            if not isinstance(payload, list):
                raise RuntimeError(f"Demands file {demands_path} is not a list")
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                src_label = entry.get("source") or entry.get("origin")
                dst_label = entry.get("destination")
                bw = entry.get("bandwidth", 0)
                if src_label is None or dst_label is None:
                    continue
                try:
                    bw_val = float(bw)
                except (TypeError, ValueError):
                    continue
                if bw_val <= 0:
                    continue
                priority = int(entry.get("priority", 1) or 1)
                max_latency = int(entry.get("max_latency", entry.get("latency", 750)) or 750)
                demand_obj = Demand(int(src_label), int(dst_label), int(round(bw_val)), priority, 10, max_latency)
                demand_obj.service = entry.get("service")
                demands.append(demand_obj)

            if not demands:
                raise RuntimeError(f"No valid demands found in {demands_path}")

            # Build a routing env to derive per-step capacities/SNR-driven scaling
            traj_glob = args.get("trajectories_glob", "flight_trajectory/dataframe/flight_simulation/*.parquet")
            env_hint = getattr(self, "env", None)
            share_root = getattr(env_hint, "agi_share_dir", None)
            traj_base = Path(share_root).expanduser() if share_root else data_in.parent
            rt_env = TimeRoutingEnv(
                demands=[
                    {
                        "source": d.source,
                        "destination": d.destination,
                        "bandwidth": d.bw,
                        "priority": getattr(d, "priority", 1),
                        "max_latency": getattr(d, "max_latency", 750),
                        "service": getattr(d, "service", None),
                    }
                    for d in demands
                ],
                demands_path=demands_path,
                trajectories_glob=traj_glob,
                sat_trajectories_glob=sat_glob,
                trajectories_base=traj_base,
                time_horizon=time_horizon,
            )

            flyenv = Flyenv()
            solver = MILP(flyenv, logger=logging.getLogger(__name__))

            step_logs = []
            # Use env time grid to align with capacities
            for t_idx in range(time_horizon):
                caps, _ = rt_env._pair_capacities(rt_env.time_grid[min(t_idx, len(rt_env.time_grid) - 1)])
                cap_max = float(np.nanmax(caps)) if np.isfinite(caps).any() else 1.0
                if cap_max <= 0:
                    cap_max = 1.0
                # Scale demands by capacity ratio
                scaled_demands: list[Demand] = []
                for d, cap in zip(demands, caps):
                    ratio = 0.0 if not np.isfinite(cap) else max(0.0, float(cap) / cap_max)
                    bw_scaled = max(1, int(round(d.bw * ratio))) if ratio > 0 else 1
                    scaled_demands.append(
                        Demand(d.source, d.destination, bw_scaled, d.priority, d.max_packet_loss, d.max_latency)
                    )
                # Build a time-varying graph snapshot: update edge capacities based on LOS caps
                graph = base_graph.copy()
                # Map demand pairs to capacities; for simplicity, apply to all edges between src/dst
                for d, cap in zip(demands, caps):
                    if not np.isfinite(cap):
                        continue
                    if graph.has_edge(d.source, d.destination):
                        for _, _, data in graph.edges(d.source, d.destination, data=True):
                            data["capacity"] = float(cap)
                    if graph.has_edge(d.destination, d.source):
                        for _, _, data in graph.edges(d.destination, d.source, data=True):
                            data["capacity"] = float(cap)

                flyenv.generate_environment_from_graph(graph, [d.bw for d in scaled_demands])
                allocations = solver.solve(scaled_demands)
                step_logs.append(
                    {
                        "time_index": t_idx,
                        "allocations": [
                            {
                                "source": alloc.demand.source,
                                "destination": alloc.demand.destination,
                                "bandwidth": alloc.demand.bw,
                                "delivered_bandwidth": alloc.delivered_bandwidth,
                                "routed": alloc.routed,
                                "path": alloc.path,
                                "latency": alloc.latency,
                                "capacity_mbps": cap,
                            }
                            for alloc, cap in zip(allocations, caps)
                        ],
                        "capacity_mbps": caps.tolist() if hasattr(caps, "tolist") else [],
                    }
                )

            outfile = data_out / "allocations_steps.json"
            outfile.write_text(json.dumps(step_logs, indent=2), encoding="utf-8")
            return {"allocations_file": str(outfile), "steps": len(step_logs), "demands": len(demands)}

        except Exception as e:
            logging.error(f"trainer_ilp_stepper error: {e}")
            traceback.print_exc()

    def trainer_PPO_manual(self, args, prev_result):
        try:
            if isinstance(args, SimpleNamespace):
                args = dict(vars(args))
            PPO_folder = self._output_root()/"trainer_PPO_manual"
            os.makedirs(PPO_folder,exist_ok=True)
            os.makedirs(PPO_folder/"tensorboard",exist_ok=True)
            logging.info(f"creating the folder '{PPO_folder}'")
            path,folder_name = create_incremented_folder(PPO_folder,"PPO_model",True)
            # envs = [make_env(seed=i) for i in range(8)]
            # env = SubprocVecEnv(envs)
            model = train_manual_PPO(args["learning_rate"],args["total_steps"],path,PPO_folder/"tensorboard"/folder_name)
            logging.info(f"Save the model in '{model}'")
            mean_reward,std_reward = evaluate_model_torch(model)
            args["mean_reward"] = mean_reward
            args["std_reward"] = std_reward
            json.dump(args, open(path/"PPO_args.json","w"))
            return args
        except Exception as e:
            logging.error(f'SB3Trainer.trainer_PPO error: {e}')
            traceback.print_exc()

    def trainer_routing(self, args, prev_result):
        """Train a simple PPO agent on the time-stepped routing env and export per-step allocations."""
        try:
            if isinstance(args, SimpleNamespace):
                args = dict(vars(args))

            seed = int(args.get("seed", 0))
            total_timesteps = int(args.get("total_timesteps", 2_000))
            time_horizon = int(args.get("time_horizon", 16))
            data_in = Path(args.get("data_in", "network_sim/dataframe")).expanduser()
            if not data_in.is_absolute():
                env = getattr(self, "env", None)
                share = getattr(env, "agi_share_dir", None)
                if share:
                    data_in = Path(share).expanduser() / data_in
            trajectories_glob = args.get(
                "trajectories_glob",
                "flight_trajectory/dataframe/flight_simulation/*.parquet",
            )
            data_out = self._output_root() / "trainer_routing"
            data_out.mkdir(parents=True, exist_ok=True)
            (data_out / "tensorboard").mkdir(parents=True, exist_ok=True)

            # Load demands (fall back to synthetic if missing)
            demands_path = args.get("demands_path") or data_in / "ilp_demands.json"
            demands = []
            try:
                demands_payload = json.loads(Path(demands_path).read_text(encoding="utf-8"))
                if isinstance(demands_payload, list):
                    demands = [d for d in demands_payload if isinstance(d, dict)]
            except Exception:
                pass
            if not demands:
                # lightweight synthetic fallback
                demands = [
                    {"source": 0, "destination": 1, "bandwidth": 500.0},
                    {"source": 1, "destination": 2, "bandwidth": 250.0},
                ]

            env = getattr(self, "env", None)
            share_root = getattr(env, "agi_share_dir", None)
            traj_base = Path(share_root).expanduser() if share_root else data_in.parent

            def _make_env():
                return TimeRoutingEnv(
                    demands=demands,
                    demands_path=demands_path,
                    time_horizon=time_horizon,
                    time_step_s=1.0,
                    trajectories_glob=trajectories_glob,
                    trajectories_base=traj_base,
                    seed=seed,
                )

            env = _make_env()
            model = PPO("MlpPolicy", env, verbose=0, seed=seed, tensorboard_log=str(data_out / "tensorboard"))
            model.learn(total_timesteps=total_timesteps, tb_log_name="routing")

            # Roll out one episode to capture per-step allocations
            obs, _ = env.reset()
            done = False
            step_logs = []
            t = 0
            while not done and t < time_horizon:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(action)
                step_logs.append(
                    {
                        "time_index": info.get("time_index", t),
                        "allocations": info.get("allocations", []),
                        "paths": info.get("paths", {}),
                        "latencies_ms": info.get("latencies_ms", []),
                        "capacity_mbps": info.get("capacity_mbps", []),
                        "delivered_mbps": info.get("delivered_mbps", []),
                        "reward": reward,
                    }
                )
                done = terminated or truncated
                t += 1

            outfile_json = data_out / "allocations_steps.json"
            outfile_json.write_text(json.dumps(step_logs, indent=2), encoding="utf-8")
            try:
                import pandas as pd

                rows = []
                for entry in step_logs:
                    t_idx = entry.get("time_index", 0)
                    for alloc in entry.get("allocations", []):
                        rows.append(
                            {
                                "time_index": t_idx,
                                "source": alloc.get("source"),
                                "destination": alloc.get("destination"),
                                "bandwidth": alloc.get("bandwidth"),
                                "routed": alloc.get("routed"),
                                "path": json.dumps(alloc.get("path", [])),
                                "latency_ms": alloc.get("latency_ms"),
                                "capacity_mbps": alloc.get("capacity_mbps"),
                            }
                        )
                if rows:
                    df = pd.DataFrame(rows)
                    df.to_parquet(data_out / "allocations_steps.parquet", index=False)
            except Exception as exc:
                logging.warning("Failed to write parquet allocations: %s", exc)

            return {"allocations_file": str(outfile_json), "steps": len(step_logs), "demands": len(demands)}

        except Exception as e:
            logging.error(f"trainer_routing error: {e}")
            traceback.print_exc()
    def stop(self):
        """
        Stop the current action.

        Raises:
            NotImplementedError: This method needs to be implemented in a subclass.
        """
        super().stop()

    # -----------------------------
    # Graph message-passing trainer
    # -----------------------------
    def trainer_gnn(self, args, prev_result):
        """
        Supervised GNN-style allocator:
          - builds time-stepped graphs from trajectories/LOS
          - trains a lightweight message-passing network to predict per-demand allocation fractions
          - logs per-step allocations to JSON/Parquet
        """
        try:
            if isinstance(args, SimpleNamespace):
                args = dict(vars(args))

            env_cfg = getattr(self, "env", None)
            share = getattr(env_cfg, "agi_share_dir", None)
            data_in = Path(args.get("data_in", "network_sim/dataframe")).expanduser()
            if not data_in.is_absolute() and share:
                data_in = Path(share).expanduser() / data_in
            data_out = self._output_root() / "trainer_gnn"
            data_out.mkdir(parents=True, exist_ok=True)

            demands_path = args.get("demands_path") or data_in / "ilp_demands.json"
            traj_glob = args.get("trajectories_glob") or "flight_trajectory/dataframe/flight_simulation/*.parquet"
            sat_traj_glob = args.get("sat_trajectories_glob") or "sat_trajectory/dataframe/flight_simulation/*.parquet"
            time_horizon = int(args.get("time_horizon", 16))
            epochs = int(args.get("epochs", 80))
            hidden_dim = int(args.get("hidden_dim", 64))
            layers = int(args.get("layers", 2))
            lr = float(args.get("learning_rate", 1e-3))
            max_paths = int(args.get("max_paths", 3))
            seed = int(args.get("seed", 0))

            torch.manual_seed(seed)
            np.random.seed(seed)

            env = TimeRoutingEnv(
                demands_path=str(demands_path),
                trajectories_glob=str(traj_glob),
                trajectories_base=share,
                sat_trajectories_glob=str(sat_traj_glob),
                time_horizon=time_horizon,
                max_paths=max_paths,
                predictive_alpha=float(args.get("predictive_alpha", 0.7)),
                predictive_min_factor=float(args.get("predictive_min_factor", 0.5)),
                history_length=int(args.get("history_length", 8)),
            )

            def _build_snapshot(step_idx: int):
                t = env.time_grid[min(step_idx, len(env.time_grid) - 1)]
                G, _ = env._build_graph(t)
                if G.number_of_edges() == 0 or G.number_of_nodes() == 0:
                    return None
                paths = env._candidate_paths(G)
                nodes = sorted(G.nodes())
                node_index = {nid: idx for idx, nid in enumerate(nodes)}

                edge_index = []
                edge_feats = []
                cap_max = 1e-6
                lat_max = 1e-6
                for u, v, data in G.edges(data=True):
                    cap = float(data.get("capacity", 0.0))
                    lat = float(data.get("latency", 0.0))
                    cap_max = max(cap_max, cap)
                    lat_max = max(lat_max, lat)
                    edge_index.append([node_index[u], node_index[v]])
                    edge_feats.append([cap, lat])
                if not edge_index:
                    return None
                cap_den = cap_max if cap_max > 0 else 1.0
                lat_den = lat_max if lat_max > 0 else 1.0
                edge_feats = np.asarray(edge_feats, dtype=np.float32)
                edge_feats[:, 0] /= cap_den
                edge_feats[:, 1] /= lat_den

                node_feats = []
                for nid in nodes:
                    out_edges = G.out_edges(nid, data=True)
                    in_edges = G.in_edges(nid, data=True)
                    out_cap = sum(float(data.get("capacity", 0.0)) for _u, _v, data in out_edges)
                    in_cap = sum(float(data.get("capacity", 0.0)) for _u, _v, data in in_edges)
                    node_feats.append(
                        [
                            float(G.out_degree(nid)),
                            float(G.in_degree(nid)),
                            out_cap / cap_den,
                            in_cap / cap_den,
                        ]
                    )
                node_feats = np.asarray(node_feats, dtype=np.float32)
                if node_feats.size:
                    for col in range(node_feats.shape[1]):
                        denom = float(np.max(node_feats[:, col])) or 1.0
                        node_feats[:, col] /= max(denom, 1.0)

                demand_pairs = []
                demand_feats = []
                targets = []
                demand_meta = []

                bw_max = 1e-6
                pr_max = 1e-6
                lat_target_max = 1e-6
                raw_feats = []
                for idx, d in enumerate(env.demands):
                    src = int(d.get("source", 0))
                    dst = int(d.get("destination", 0))
                    if src not in node_index or dst not in node_index:
                        continue
                    bw = float(d.get("bandwidth", 0.0))
                    pr = float(d.get("priority", 1.0))
                    lat_t = float(d.get("max_latency", 750))
                    bw_max = max(bw_max, bw)
                    pr_max = max(pr_max, pr)
                    lat_target_max = max(lat_target_max, lat_t)
                    target = 0.0
                    if idx in paths:
                        cap = float(paths[idx].get("path_capacity", 0.0) or 0.0)
                        target = max(0.0, min(1.0, cap / max(bw, 1e-6)))
                    path_capacity = float(paths.get(idx, {}).get("path_capacity", 0.0) or 0.0)
                    demand_pairs.append([node_index[src], node_index[dst]])
                    raw_feats.append([bw, pr, lat_t])
                    targets.append(target)
                    demand_meta.append(
                        {
                            "source": src,
                            "destination": dst,
                            "bandwidth": bw,
                            "path": paths.get(idx, {}).get("selected_path", []),
                            "path_capacity": path_capacity,
                        }
                    )

                if not demand_pairs:
                    return None

                for bw, pr, lat_t in raw_feats:
                    demand_feats.append(
                        [
                            bw / max(bw_max, 1.0),
                            pr / max(pr_max, 1.0),
                            lat_t / max(lat_target_max, 1.0),
                        ]
                    )

                return {
                    "time_index": step_idx,
                    "node_feats": torch.tensor(node_feats, dtype=torch.float32),
                    "edge_index": torch.tensor(edge_index, dtype=torch.long).t().contiguous(),
                    "edge_feats": torch.tensor(edge_feats, dtype=torch.float32),
                    "demand_pairs": torch.tensor(demand_pairs, dtype=torch.long),
                    "demand_feats": torch.tensor(demand_feats, dtype=torch.float32),
                    "targets": torch.tensor(targets, dtype=torch.float32),
                    "demand_meta": demand_meta,
                }

            snapshots = []
            for step_idx in range(min(time_horizon, len(env.time_grid))):
                snap = _build_snapshot(step_idx)
                if snap:
                    snapshots.append(snap)

            if not snapshots:
                raise RuntimeError("No valid graph snapshots found for GNN training.")

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model = GraphAllocNet(
                node_feat_dim=4,
                edge_feat_dim=2,
                demand_feat_dim=3,
                hidden=hidden_dim,
                layers=layers,
            ).to(device)
            opt = optim.Adam(model.parameters(), lr=lr)
            loss_fn = nn.SmoothL1Loss()

            for epoch in range(max(1, epochs)):
                total_loss = 0.0
                for snap in snapshots:
                    opt.zero_grad()
                    preds = model(
                        snap["node_feats"].to(device),
                        snap["edge_index"].to(device),
                        snap["edge_feats"].to(device),
                        snap["demand_pairs"].to(device),
                        snap["demand_feats"].to(device),
                    )
                    targets = snap["targets"].to(device)
                    loss = loss_fn(preds, targets)
                    loss.backward()
                    opt.step()
                    total_loss += float(loss.item())
                if (epoch + 1) % max(1, epochs // 4) == 0:
                    logging.info("GNN epoch %d/%d | loss=%.6f", epoch + 1, epochs, total_loss / len(snapshots))

            # Inference + logging
            step_logs = []
            with torch.no_grad():
                for snap in snapshots:
                    preds = model(
                        snap["node_feats"].to(device),
                        snap["edge_index"].to(device),
                        snap["edge_feats"].to(device),
                        snap["demand_pairs"].to(device),
                        snap["demand_feats"].to(device),
                    ).cpu().numpy()
                    entry = {"time_index": snap["time_index"], "allocations": []}
                    for pred, meta in zip(preds.tolist(), snap["demand_meta"]):
                        frac = float(np.clip(pred, 0.0, 1.0))
                        entry["allocations"].append(
                            {
                                "source": meta["source"],
                                "destination": meta["destination"],
                                "bandwidth": meta["bandwidth"],
                                "predicted_fraction": frac,
                                "target_fraction": float(np.clip(meta.get("path_capacity", 0.0) / max(meta["bandwidth"], 1e-6), 0.0, 1.0)),
                                "path": meta.get("path", []),
                                "path_capacity": meta.get("path_capacity"),
                                "delivered_mbps": frac * meta["bandwidth"],
                            }
                        )
                    step_logs.append(entry)

            outfile_json = data_out / "allocations_steps.json"
            outfile_json.write_text(json.dumps(step_logs, indent=2), encoding="utf-8")
            try:
                import pandas as pd

                rows = []
                for entry in step_logs:
                    t_idx = entry.get("time_index", 0)
                    for alloc in entry.get("allocations", []):
                        rows.append(
                            {
                                "time_index": t_idx,
                                "source": alloc.get("source"),
                                "destination": alloc.get("destination"),
                                "bandwidth": alloc.get("bandwidth"),
                                "predicted_fraction": alloc.get("predicted_fraction"),
                                "target_fraction": alloc.get("target_fraction"),
                                "path": json.dumps(alloc.get("path", [])),
                                "path_capacity": alloc.get("path_capacity"),
                                "delivered_mbps": alloc.get("delivered_mbps"),
                            }
                        )
                if rows:
                    pd.DataFrame(rows).to_parquet(data_out / "allocations_steps.parquet", index=False)
            except Exception as exc:  # pragma: no cover - optional parquet write
                logging.warning("Failed to write parquet allocations for GNN: %s", exc)

            torch.save(model.state_dict(), data_out / "gnn_policy.pt")
            return {"allocations_file": str(outfile_json), "steps": len(step_logs), "demands": len(env.demands)}
        except Exception as e:
            logging.error(f"trainer_gnn error: {e}")
            traceback.print_exc()

    # Backward compatibility for legacy name
    def trainer_gnn_stub(self, args, prev_result):
        return self.trainer_gnn(args, prev_result)
