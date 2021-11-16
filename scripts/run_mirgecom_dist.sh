#!/bin/bash

exename="${1}"
options="${2}"
numparts="${3}"

printf "Resetting cache directories.\n"
export PYOPENCL_CTX="0:1"
export XDG_CACHE_HOME="/tmp/$USER/xdg-scratch"
export POCL_CACHE_DIR="/tmp/$USER/pocl-cache"
rm -rf $XDG_CACHE_HOME $POCL_CACHE_DIR

printf "Checking task info:\n"
jsrun -r 1 -g 1 -a 1 -n ${numparts} js_task_info

printf "Running: jsrun -g 1 -a 1 -n ${numparts} python -O -u -m mpi4py ./${exename} ${options}\n"
jsrun -g 1 -a 1 -r 1 -n ${numparts} python -O -u -m mpi4py ./${exename} ${options}
