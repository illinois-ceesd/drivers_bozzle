#!/bin/bash

exename="${1}"
options="${2}"

printf "Resetting cache directories.\n"
export PYOPENCL_CTX="0:1"
export XDG_CACHE_HOME="/tmp/$USER/xdg-scratch"
export POCL_CACHE_DIR="/tmp/$USER/pocl-cache"
rm -rf $XDG_CACHE_HOME $POCL_CACHE_DIR

printf "Running: jsrun -g 1 -a 1 -n 1 python -O -u -m mpi4py ./${exename} ${options}\n"
jsrun -g 1 -a 1 -n 1 python -O -u -m mpi4py ./${exename} ${options}
