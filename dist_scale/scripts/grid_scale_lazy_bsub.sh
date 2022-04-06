#!/bin/bash --login

#BSUB -nnodes 1
#BSUB -G uiuc
#BSUB -W 480
#BSUB -J combozzle_lazy_gridscale
#BSUB -q pbatch

. ./mirge_batch_env.sh
. ${EMIRGE_HOME}/config/activate_env.sh

config_files="./run_config/*.yaml"
for file in $config_files
do
    printf "python -m mpi4py ./combozzle.py -i ${file} --lazy\n"
    python -m mpi4py ./combozzle.py -i $file --lazy
done

mkdir -p run_logs
mv *sqlite run_logs

