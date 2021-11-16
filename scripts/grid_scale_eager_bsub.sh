#!/bin/bash --login

#BSUB -nnodes 1
#BSUB -G uiuc
#BSUB -W 720
#BSUB -J bozzle_eager_gridscale
#BSUB -q pbatch
#BSUB -o bozzle-eager-gridscale.out

source /p/gpfs1/mtcampbe/CEESD/AutomatedTesting/MIRGE-Timing/hand-timing/emirge/config/activate_env.sh
./run_order_scale_eager.sh
