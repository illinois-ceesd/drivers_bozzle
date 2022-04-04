Each directory here contains a test suite intended to run and capture
grid-scaling experiemnts for _MIRGE-Com_.

In each experiment directory you should find the following:

- config: directory containing all the yaml file inputs for combozzle
- run_logs: directory containing the data produced by actual runs
- *bsub.sh*: a script containing the Lassen batch job used to create the data
- combozzle.py: a symlink to the main combozzle python driver

In general, to run any given experiment on Lassen:
(warning: this will overwrite any data in the `run_logs` directory.)

> bsub *bsub.sh

