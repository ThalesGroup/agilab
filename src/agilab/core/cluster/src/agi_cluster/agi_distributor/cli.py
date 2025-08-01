import sys
import logging

logger = logging.getLogger(__name__)

USAGE = """
Usage: python cli.py <cmd> [arg]

Commands:
  kill [exclude_pids]      Kill processes, excluding comma-separated PIDs (optional)
  clean <wenv_path>        Clean the given wenv directory
  unzip <wenv_path>        Unzip resources into the given wenv directory
  threaded                 Run the Python threads test
  platform                 Show Python platform/version info

Examples:
  python cli.py kill
  python cli.py kill 1234,5678
  python cli.py clean /path/to/wenv
  python cli.py unzip /path/to/wenv
  python cli.py threaded
  python cli.py platform
"""

if __name__ == "__main__":
    # If no arguments provided, print usage and exit
    if len(sys.argv) == 1:
        print(USAGE)
        sys.exit(1)

    cmd = sys.argv[1]
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    exclude_pids = set()

    if cmd == "kill":
        if arg:
            for pid_str in arg.split(","):
                try:
                    exclude_pids.add(int(pid_str))
                except Exception:
                    logger.warning(f"Invalid PID to exclude: {pid_str}")
        kill(exclude_pids=exclude_pids)
    elif cmd == "clean":
        if not arg:
            print("Missing argument for 'clean'\n" + USAGE)
            sys.exit(1)
        clean(wenv=arg)
    elif cmd == "unzip":
        if not arg:
            print("Missing argument for 'unzip'\n" + USAGE)
            sys.exit(1)
        unzip(wenv=arg)
    elif cmd == "threaded":
        test_python_threads()
    elif cmd == "platform":
        python_version()
    else:
        print(f"Unknown command: {cmd}\n{USAGE}")
        sys.exit(1)
