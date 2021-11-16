# drivers_bozzle

Scalable test case

Bozzle (bozzle.py) is a production-adjacent performance testing driver
that is constructed by using a simple box mesh generator in place of
the production driver (nozzle.py) gmsh-based grid generator. The bozzle
driver, like the production drivers, requires the production branch of
MIRGE-Com in order to run.

By default, it uses order 1 elements, RK4, Navier-Stokes, and artificial 
viscosity. It is a single air-like gas (i.e. no mixture species).  The
solution init, bcs, and time-dependent injection features match those used
by the production driver nozzle.py.

This is all set up to run on Lassen. The *bsub* scripts are designed to
be submitted with `bsub <script>` on Lassen.  
--------
eager_weak_bsub.sh: Run an eager weak scaling test
grid_scale_{eager,lazy}_bsub.sh: Run {eager, lazy} grid scaling test

The support scripts are as follows:
--------
3 supporting scripts used by the *bsub* scripts.
run_eager_weak.sh: loop over orders and scales for weak MPI scaling with eager
run_order_scale_{eager,lazy}.sh: loop over orders and grid scales

2 scripts to run MIRGE-Com itself used by all/most others:
run_mirgecom.sh: Run on one GPU
run_mirgecom_dist.sh: Distribute to multiple GPUs with MPI

1 script to generate an input YAML file read by bozzle.py:
generate_input_yaml.sh

several scripts for post-processing the data into sqlite/yaml files:
create_db_summary.sh: runs runalyzer to gather sqlite data
generate_yaml_run_file.sh: create run-specific yaml data
extract_timing_data.sh: extracts the run timing data from sqlite into global yaml

Several yaml-input-based options have been added for use in exploring
the behavior of MIRGE-Com:

wscale: Grid scaling param (nelem approx = 384*scale) default[1]
hScaling: Scale physical box extent by *weak_scale* (0) , or not (1) default[1] 
gridOnly: generate the grid and (0) step, or (1) exit default[0]
discrOnly: generate the grudge discretization and (0) step, or (1) exit default[0]
initOnly: exit after initialization (1) or continue to stepping (0) default[0]
boundaryReport: generate a report abt npts/boundary (1), or not (0) default[0]
