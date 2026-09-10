# Benchmark and Generated-Test Review

Use the benchmark section for performance claims or benchmark changes. Use the
generator section when fixtures, factories or property strategies change the
inputs supplied to tests. A normal bug fix needs neither a new benchmark nor a
property-testing dependency merely because this reference exists.

## Benchmark Evidence

First identify the question and measured boundary. A worker kernel, public
reducer operation, Python/native conversion, UI rerun and complete workflow
measure different costs even when they process the same dataset.

| Question | Evidence needed |
| --- | --- |
| Does cost grow unexpectedly with input size? | Geometrically spaced sizes, fixed remaining dimensions, repeated measurements and cross-size ratios. |
| Did this revision slow down a fixed workload? | Same input, boundary, build/dependencies and runner conditions on both revisions; correctness checks and timing variability. |
| Where does this workload spend time? | A profile of a fixed input with absolute costs and the expected call path; percentages guide investigation. |
| Is the validation workflow affordable? | Dependency/setup/build, benchmark execution and whole-job time reported separately, including cache state. |

For each benchmark family, record the suspected regression, originating issue
or change, measured operation, variable input dimensions, expected cost growth,
input/seed identity, setup included or excluded, environment/build, repetitions,
and acceptable runtime budget. Keep this beside the existing benchmark/report or
in PR evidence; a new reporting framework is unnecessary.

For a scaling claim, normally measure at least three sizes such as N, 2N and 4N,
with enough work to distinguish growth from startup and timer noise. Compare
adjacent measurements using `p = log(T2 / T1) / log(N2 / N1)` when times are
positive and resolved above noise. An exponent near one is consistent with
linear growth over those measurements; near two suggests quadratic growth.
Report uncertainty and the tested range. Finite samples do not prove asymptotic
complexity, and tiny overhead-dominated inputs cannot establish scaling.

Check the implementation's cost model as well as the timings. Repeatedly copying
an expanding accumulator can add quadratic work even when each incoming batch
is fixed-size. Keep batch count and batch size separate. A profile can help
explain a timing change, but a lower percentage for one function does not alone
establish that the operation became faster.

Reuse the nearest AGILAB harness after inspecting its timing boundary:

- `tools/reduce_contract_benchmark.py` checks a public reducer artifact. Its
  timer includes construction of deterministic partial payloads. Increasing
  `items_per_partial` increases that preparation work; the reducer receives
  aggregate payloads, not one entry per original item. This harness alone does
  not isolate reducer scaling with raw item count.
- `tools/benchmark_execution_playground.py` compares worker execution paths.
  Inspect whether its worker initialization, preparation and execution cover
  the cost the user reported before choosing it for a kernel-only claim.
- `tools/benchmark_execution_pandas_cython_kernel.py` targets the Pandas/Cython
  boundary. Check the current build and arguments before comparing results.

Run Python through the repository's managed `uv` environment. Preserve existing
app/runtime setup; inspect `--help` and output destinations before running a
harness. Keep raw results in the established ignored report directory and put
only the useful comparison and artifact location in the close-out.

Retain an automatic benchmark when it detects a named regression within a
reasonable local/CI budget. Keep large profiling workloads as optional
diagnostics unless they also justify a recurring regression check. Use AGILAB's
existing local-first validation policy and actual measured cost to choose run
frequency. Do not change CI triggers or add a service merely to obtain a profile.

## Generated-Test Input Domains

State the property and its preconditions before changing a generator. For
example, an artifact round-trip test may require JSON-compatible payloads,
whereas a constructor rejection test intentionally supplies invalid input.

When a default fixture/factory/strategy changes:

1. Find callers with `rg`, including wrappers, parametrized tests, examples,
   benchmarks and runtime/demo helpers that share the generator.
2. Decide whether each caller's property covers the expanded input space. A
   caller left on the default now makes that broader test claim; it cannot be
   treated as unaffected simply because its source did not change.
3. Give narrower preconditions explicit names, such as `json_compatible_payload`
   or `nonempty_partials`, using existing factories or strategies. Validate the
   named restriction with the relevant round-trip or contract test. Broad
   filtering must not silently erase the cases the change intended to add.
4. Exercise the changed dimensions, including absent/present optional fields,
   empty/nonempty collections and relevant invalid/boundary values. Distinguish
   randomly varied dimensions from fixed injected metadata; one fixed example
   provides smoke coverage for that dimension.
5. Construct valid cases through the API that owns their invariants. For negative
   tests, make deliberate invalid construction and the expected rejection
   explicit. Recheck invariants after generator post-processing; preserve small
   counterexamples and shrinking when the framework supports it.
6. Run the affected suites through the existing targeted validation path. Record
   seeds or replay examples and retain a minimized regression for a discovered
   failure. Passing generated samples is evidence for those samples, not proof
   over the whole domain. Report unavailable coverage explicitly.

Apply these rules to current pytest factories and parametrized tests as well as
to property-testing frameworks when already used. For a small finite boundary
set, explicit pytest cases may be sufficient. Avoid changing shared fixture
defaults to fix one caller when that caller should state its own precondition.

## Source Notes

This is original AGILAB guidance informed by the OMMX skills reviewed at commit
`1ffaf60117cba1b447e2c98ea608544d7f6fcc8d`:

- [benchmark-review](https://github.com/Jij-Inc/ommx/blob/1ffaf60117cba1b447e2c98ea608544d7f6fcc8d/.agents/skills/benchmark-review/SKILL.md)
- [proptest-arbitrary-review](https://github.com/Jij-Inc/ommx/blob/1ffaf60117cba1b447e2c98ea608544d7f6fcc8d/.agents/skills/proptest-arbitrary-review/SKILL.md)

Upstream licensing is recorded in
[LICENSE-MIT](https://github.com/Jij-Inc/ommx/blob/1ffaf60117cba1b447e2c98ea608544d7f6fcc8d/LICENSE-MIT)
and [LICENSE-APACHE](https://github.com/Jij-Inc/ommx/blob/1ffaf60117cba1b447e2c98ea608544d7f6fcc8d/LICENSE-APACHE).
