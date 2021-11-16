#!/bin/bash

timestamp=$(date "+%Y.%m.%d-%H.%M.%S")
TIMING_HOME=$(pwd)
TIMING_HOST=$(hostname)
TIMING_PLATFORM=$(uname)
TIMING_ARCH=$(uname -m)
TIMING_HOST="Lassen"
GPU_ARCH="GV100GL"
EXENAME="bozzle.py"
CASENAME="bozzle-eager-weak"
RUN_OPTIONS="-c ${CASENAME} --log"
RUN_LOG_FILE="${CASENAME}-rank0.sqlite"

# Do for orders 1, 2, 3
for order in {1..3}
do
    YAML_FILE_NAME="${CASENAME}_p${order}.yaml"
    rm -f ${YAML_FILE_NAME}

    # The grid scales like this:
    # NumElements = 6*[INT(4*(scale)**(1/3)]**3
    for scale in 1 2 4 8 16 32
    do
        SUMMARY_FILE_ROOT="${CASENAME}_p${order}w${scale}"
        SUMMARY_FILE_NAME="${SUMMARY_FILE_ROOT}_${timestamp}.sqlite"

        date

        rm -f gridscale_params.yaml
        printf "Generating input file...\n"
        ./generate_input_yaml.sh ${order} ${scale} gridscale_params.yaml
        cat gridscale_params.yaml
        MY_OPTIONS="-i gridscale_params.yaml ${RUN_OPTIONS}" 
        printf "Running ${EXENAME} with order=${order}, scale=${scale}\n"
        ./run_mirgecom_dist.sh "${EXENAME}" "${MY_OPTIONS}" "${scale}"
        date

        if [[ -f "${RUN_LOG_FILE}" ]]; then

            printf "Done running ${EXENAME} with order=${order}, scale=${scale}\n"
            printf "Creating DB summary...\n"

            # -- Process the results of the timing run
            ./create_db_summary.sh ${RUN_LOG_FILE} ${SUMMARY_FILE_NAME}
 
            YAML_RUN_FILE="${SUMMARY_FILE_ROOT}_${timestamp}.yaml"
            ./generate_yaml_run_file.sh ${SUMMARY_FILE_NAME} ${YAML_RUN_FILE} ${order} ${scale}

            if [[ -f ${YAML_FILE_NAME} ]]; then
                cat ${YAML_RUN_FILE} >> ${YAML_FILE_NAME}
            else
                cp ${YAML_RUN_FILE} ${YAML_FILE_NAME}
            fi

        else
            printf "The expected file: ${RUN_LOG_FILE} was not created.\n"
        fi
    done
done
