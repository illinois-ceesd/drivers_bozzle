# drivers_bozzle

Scalable prediction-adjacent testing application.  The drivers in this
driver suite are intended to exercise all of the features used in 
the _MIRGE-Com_ prediction runs at CEESD.

Combozzle (combozzle.py) is a production-adjacent performance testing driver
that is constructed by using a simple box mesh generator in place of
the production driver (isolator.py) gmsh-based grid generator. The combozzle
driver, like the production drivers, requires the `production` branch of
_MIRGE-Com_ in order to run.

The `combozzle.py` driver is the main driver.  The features and 
(optional) features are roughly as follows:

- MPI: 1 rank (n ranks)
- DT: fixed (fixed cfl)
- Timestepping: Euler (rk4, rk54)
- RHS: Navier-Stokes (Euler, dummy)
- EOS: Mixture (nspecies inert, single gas)
- Shock cap: Laplacian AV (off)
- Additional: Sponge (off)

All features used by _MIRGE-Com_ in the CEESD prediction runs
are ON by default.  The many parameters for the configuration
of features and run details can be found near the top of the 
`main` function in `combozzle.py`.  The code can also read config
parameters from YAML files.

--------------------

Most of the subdirectories contain experiments  set up to run on Lassen@LLC.
The *bsub* scripts are designed to be submitted with `bsub <script>` on Lassen.
Further descriptions for each experiment should be found in README in the 
experiment-specific directories.

--------------

Local files and directories:

combozzle.py: the main driver
grid_scale: directory containing grid-scaling experiments
scripts: a parking area for scripts used to build up experiments
config: sample yaml input
