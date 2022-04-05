#!/bin/bash

export PYOPENCL_CTX="port:tesla"
export XDG_CACHE_HOME="/tmp/$USER/xdg-scratch"
export POCL_CACHE_DIR_ROOT="/tmp/$USER/pocl-cache"
export EMIRGE_HOME="/p/gpfs1/mtcampbe/CEESD/AutomatedTesting/MIRGE-Timing/timing/emirge.fusion"

nnodes=$(echo $LSB_MCPU_HOSTS | wc -w)
nnodes=$((nnodes/2-1))
nproc=$((4*nnodes)) # 4 ranks per node, 1 per GPU

export MIRGE_NODES=$nnodes
export MIRGE_NRANKS=$nproc

jsrun_cmd="jsrun -g 1 -a 1 -n $nproc"

export MIRGE_JSRUN=$jsrun_cmd
# Fixes https://github.com/illinois-ceesd/mirgecom/issues/292
# (each rank needs its own POCL cache dir)

# Print task allocation
# $jsrun_cmd js_task_info

# echo "----------------------------"

# Run application
# -O: switch on optimizations
# POCL_CACHE_DIR=...: each rank needs its own POCL cache dir
# $jsrun_cmd bash -c 'POCL_CACHE_DIR=$POCL_CACHE_DIR_ROOT/$$ python -O -m mpi4py ./pulse-mpi.py'

