


# my_script.py
import argparse
import pickle
import sys
from agi_worker.agi_worker import AgiWorker

# Import your modules and functions (adjust the import paths accordingly)
from your_module import run, load_env  # Assume load_env creates your env object

def main():
    parser = argparse.ArgumentParser(
        description="Run distribution and save workers info as a pickle"
    )
    parser.add_argument("--module", action="store_true", help="Target module")
    parser.add_argument("--cond_build", action="store_true", help="Conditional build flag")
    parser.add_argument("--mode", type=int, required=True, help="Mode")
    parser.add_argument("--verbose", action="store_true", help="Verbose mode")
    parser.add_argument(
        "--output",
        type=str,
        default="log/run.pkl",
        help="Path to output pickle file (default: log/run.pkl)",
    )
    # Add additional arguments as needed, for example:
    # parser.add_argument("--arg1", type=str, help="Additional argument for run()")
    args = parser.parse_args()

    # Create or load your env. You might read a config file here.
    extra_args = args['args']

    # Run your function to get the result tuple
    result_tuple = AgiWorker.run(args['module'], mode=args.mode, verbose=args.verbose, args=extra_args)

    # Write the result to a file as a pickle
    with open(args.output, "wb") as f:
        pickle.dump(result_tuple, f)


    # Optionally, also print to stdout (or not)
    if args["verbose"] >= 0:
        sys.stdout.write("run pickle saved to: " + args.output + "\n")

if __name__ == "__main__":
    main()