# Free-threading lab

Explore a pure-Python Mandelbrot workload, then measure the unchanged AGILAB pool engine with real threads and spawned processes. The application Python and notebook cells were generated and repaired with local Qwen 3.8 27B, model ddalcu/Qwen3.8-27B-MLX-Serve-4bit. The public receipt records the exact model revisions and independent verification. A coordinating assistant prepared prompts, reviewed output and ran checks. No cloud code-generation fallback was used.

## Run

Use standard Python 3.13+ for the interface, with the dependencies in requirements.txt installed. Provide a free-threaded Python 3.14 interpreter through AGILAB_FREE_THREADING_PYTHON or python3.14t on PATH. The measured child interpreters use only the standard library and the bundled pool engine.

    python -m streamlit run app.py --server.address=127.0.0.1
    python -m pytest -q tests.py

The initial page shows a small image preview. Run analysis commits controls and calculates image statistics. Run benchmark explicitly starts measurements. Changing unsubmitted controls does not change a completed benchmark.

## Measurements

All three modes use the same free-threaded Python build and the same image:

| Mode | GIL | Pool backend |
| --- | --- | --- |
| gil_on_threads | enabled | threads |
| gil_off_threads | disabled | auto, verified as threads |
| gil_on_processes | enabled | spawned processes |

Each mode runs a one-worker baseline and the selected parallel capacity, for six cases per repeat. Repeated measurements use medians. End-to-end wall time and engine time are reported separately, with speedups relative to the matching mode's baseline. Requested workers, resolved pool width and observed active workers are different quantities; small workloads may use fewer workers than the available capacity.

The original scalar Mandelbrot algorithm uses endpoint-inclusive coordinates over [-2,1] by [-1.2,1.2]. Two-row tiles use a deterministic even/odd ordering. Every tile returns its real PID, thread identifier, runtime snapshots, monotonic timestamps and iteration counts. Reduction checks complete unique coverage. The image digest hashes each row-major count as a three-digit ASCII decimal value. The original notebook and unchanged engine have pinned SHA-256 values.

The benchmark bounds CPU allocation using available host/process/affinity/cgroup information and CPU_CORES, with a maximum of eight workers. One CPU cannot establish parallel scaling. Each child is isolated in an owned process group and temporary working directory. A nonblocking lock rejects overlapping requests. Timeouts and cancellation clean up owned processes.

## Notebook and verification

solution.ipynb contains four generated code cells: inputs and provenance, scalar reference, six real benchmark cases, and deterministic results.json. Supply PROJECT_ROOT as the extracted project directory and run the notebook in a fresh working directory. The results artifact excludes variable timings and process identities so the notebook and generated AGILAB workflow can be replayed and compared.

Source: original AGILAB benchmark notebook, September 19, 2026, BSD-3-Clause. Notices remain in LICENSE. This demonstrates the bundled pool engine on one machine; it does not establish compatibility of all AGILAB dependencies with free-threaded Python. Timings are fresh local measurements and do not guarantee acceleration on the public Space. Qwen builds the application locally; the public Space runs the completed application.
