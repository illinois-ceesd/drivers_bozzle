#!/bin/bash --login

#BSUB -nnodes 32
#BSUB -G uiuc
#BSUB -W 120
#BSUB -J bozzle_eager_weak
#BSUB -q pbatch
#BSUB -o bozzle-eager-weak.out

source /p/gpfs1/mtcampbe/CEESD/AutomatedTesting/MIRGE-Timing/hand-timing/emirge/config/activate_env.sh
./run_eager_weak.sh
