#!/bin/bash --login

#BSUB -nnodes 4
#BSUB -G uiuc
#BSUB -W 540
#BSUB -J combozzle_lazy_weakscale
#BSUB -q pbatch

. ./mirge_batch_env.sh
. ${EMIRGE_HOME}/config/activate_env.sh
set -x
for nrank in 1 2 4 8 16
do
    export CONFIG_FILE=./run_config/weak_${nrank}.yaml
    rm -f run_config.yaml
    ln -s ${CONFIG_FILE} run_config.yaml
    printf "jsrun -g 1 -a 1 -n $nrank bash -c 'POCL_CACHE_DIR=$POCL_CACHE_DIR_ROOT/$$ python -O -m mpi4py ./combozzle.py -i ${config_file} --lazy'\n"
    jsrun -g 1 -a 1 -n $nrank bash -c 'POCL_CACHE_DIR=$POCL_CACHE_DIR_ROOT/$$ python -O -m mpi4py ./combozzle.py -i run_config.yaml --lazy'
    mkdir -p run_n${nrank}_logs
    mv *sqlite run_n${nrank}_logs
done
