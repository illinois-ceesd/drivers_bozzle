#!/bin/bash

order=${1}
scale=${2}
filename=${3}
cat << EOF > ${filename}
nviz: 100
nrestart: 100
current_dt: 1e-10
t_final: 1.1e-9
alpha_sc: 0.5
s0_sc: -5.0
kappa_sc: 0.5
logDependent: 0
order: ${order}
wscale: ${scale}
EOF
