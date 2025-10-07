#!/usr/bin/env python3
"""
AGI app setup
Author: Jean-Pierre Morard
Tested on Windows, Linux and MacOS
"""

from setuptools import setup, find_packages, SetuptoolsDeprecationWarning
import warnings

warnings.filterwarnings("ignore", category=SetuptoolsDeprecationWarning)


# --- End custom command ---


def main() -> None:
    setup(
        package_dir={"": "src"},
        packages=find_packages(where="src", exclude=["test", "cluster"]),
        zip_safe=False,  # Use our custom bdist_egg command.
    )


if __name__ == "__main__":
    main()