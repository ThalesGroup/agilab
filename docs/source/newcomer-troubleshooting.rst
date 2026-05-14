Newcomer First-Failure Recovery
===============================

This page is intentionally narrow.

Use it only for the first AGILAB proof path:

- source checkout
- built-in ``flight_telemetry_project``
- local run
- web UI first

If you are already debugging cluster mode, private apps, packaged install, or
notebook-first flows, this is not the right page. Go to the broader
:doc:`troubleshooting` or :doc:`faq` pages instead.

Before anything else
--------------------

Run the newcomer proof command once and keep its result as your baseline::

    uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py

If you want the installer and seeded helper checks as part of the same proof::

    uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py --with-install

Failure 1: ``uv`` is missing
----------------------------

Symptom:

- ``uv: command not found``
- the install or newcomer proof command fails immediately before AGILAB starts

Recovery::

    curl -LsSf https://astral.sh/uv/install.sh | sh
    exec "$SHELL" -l
    uv --version

Then rerun the newcomer proof::

    uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py

Failure 2: ``./install.sh --install-apps`` fails
------------------------------------------------

Symptom:

- the installer exits non-zero
- built-in apps are not usable afterwards
- you only have partial setup under ``~/log`` or ``~/.agilab``

Recovery::

    ./install.sh --install-apps

If you need to inspect the latest installer log quickly::

    dir="$HOME/log/install_logs"; f=$(ls -1t "$dir"/*.log 2>/dev/null | head -1); [ -n "$f" ] && echo "Log: $f" && tail -n 40 "$f"

Then rerun the proof command with install enabled::

    uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py --with-install

Failure 3: the built-in app path is not found
---------------------------------------------

Symptom:

- ``Provided --active-app path not found``
- the PROJECT page does not point to the built-in flight demo
- the newcomer proof command fails before the UI smoke completes

The expected built-in path in a source checkout is::

    src/agilab/apps/builtin/flight_telemetry_project

Recovery::

    test -d src/agilab/apps/builtin/flight_telemetry_project && echo OK || echo MISSING

If it is missing, you are likely not in the AGILAB source checkout you think
you are, or the install did not finish cleanly. Return to the repo root and
rerun::

    ./install.sh --install-apps

Then rerun::

    uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py

Failure 4: the web UI or Main Page/ORCHESTRATE smoke fails
----------------------------------------------------------

Symptom:

- ``streamlit run src/agilab/main_page.py`` fails
- the newcomer proof command reports a failing ``source ui smoke`` step
- Main Page or ORCHESTRATE raises exceptions during AppTest startup

Recovery::

    uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py

If that fails, run the pages directly::

    uv --preview-features extra-build-dependencies run streamlit run src/agilab/main_page.py

Then verify the built-in app can be resolved by path::

    uv --preview-features extra-build-dependencies run python tools/apps_pages_launcher.py --active-app src/agilab/apps/builtin/flight_telemetry_project

If the failure mentions package import or missing environment setup, rerun::

    ./install.sh --install-apps

Failure 5: no fresh output appears under ``~/log/execute/flight_telemetry/``
----------------------------------------------------------------------------------------------------

Symptom:

- the UI starts, but your first proof does not end in visible evidence
- ``~/log/execute/flight_telemetry/`` has no fresh output
- install may have seeded helper scripts but no useful run artifacts appeared

First confirm the newcomer proof still passes::

    uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py --with-install

Then inspect the expected output directory::

    ls -la ~/log/execute/flight_telemetry

If the helper scripts are missing, rerun the source installer for the built-in
app::

    uv --preview-features extra-build-dependencies run python src/agilab/apps/install.py src/agilab/apps/builtin/flight_telemetry_project --verbose 1

Then relaunch the UI and follow the first-proof path again:

1. ``PROJECT`` -> select ``src/agilab/apps/builtin/flight_telemetry_project``
2. ``ORCHESTRATE`` -> run the local install/distribute/run path
3. confirm fresh output exists under ``~/log/execute/flight_telemetry/``
4. ``ANALYSIS`` -> confirm one visible result exists

When you are past the newcomer hurdle
-------------------------------------

You are done with this page when all of the following are true:

- the newcomer proof command returns ``PASS``
- AGILAB writes fresh output under ``~/log/execute/flight_telemetry/``
- the first-proof path stays understandable as
  ``PROJECT -> ORCHESTRATE -> ANALYSIS``

After that, go back to:

- :doc:`newcomer-guide`
- :doc:`quick-start`
- :doc:`distributed-workers` only if you are ready to leave the local path
