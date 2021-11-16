#!/bin/bash

SUMMARY_FILE_NAME="${1}"
STARTUP_TIME=$(runalyzer -m ${SUMMARY_FILE_NAME} -c 'print(q("select $t_init.max").fetchall()[0][0])' | grep -v INFO)
FIRST_STEP=$(runalyzer -m ${SUMMARY_FILE_NAME} -c 'print(sum(p[0] for p in q("select $t_step.max").fetchall()[0:1]))' | grep -v INFO)
MIDDLE_8_STEPS=$(runalyzer -m ${SUMMARY_FILE_NAME} -c 'print(sum(p[0] for p in q("select $t_step.max").fetchall()[2:9]))' | grep -v INFO)
printf "==== ${rawfile_name} -> ${SUMMARY_FILE_NAME} ====\n"
printf "STARTUP:     ${STARTUP_TIME}\n"
printf "FIRST_STEP:  ${FIRST_STEP}\n"
printf "MIDDLE 8 STEPS: ${MIDDLE_8_STEPS}\n"

