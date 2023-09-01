set -euxo pipefail

black --diff mytools tests
isort -c mytools tests

pytest

mypy -p mytools
