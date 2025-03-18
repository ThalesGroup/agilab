import argparse
import sys
from pathlib import Path
import streamlit.web.cli as stcli


def main():
    parser = argparse.ArgumentParser(
        description="Run AGILAB application with custom options."
    )
    parser.add_argument(
        "--cluster-credentials", type=str, help="Cluster account user:password", default=None
    )
    parser.add_argument(
        "--openai-api-key", type=str, help="OpenAI API key", default=None
    )
    # Parse known arguments; extra arguments are captured in `unknown`
    args, unknown = parser.parse_known_args()

    # Determine the target script (adjust path if necessary)
    target_script = str(Path(__file__).parent / "AGILAB.py")

    # Build the base argument list for Streamlit.
    new_argv = ["streamlit", "run", target_script]

    # Collect custom arguments.
    custom_args = []
    if args.cluster_credentials is not None:
        custom_args.extend(["--cluster-credentials", args.cluster_credentials])
    if args.openai_api_key is not None:
        custom_args.extend(["--openai-api-key", args.openai_api_key])
    if unknown:
        custom_args.extend(unknown)

    # Only add the double dash and custom arguments if there are any.
    if custom_args:
        new_argv.append("--")
        new_argv.extend(custom_args)

    sys.argv = new_argv
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()