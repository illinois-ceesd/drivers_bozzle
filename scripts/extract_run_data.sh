#!/bin/bash

RAWFILE_ROOT="${1}"
RAWFILE_NAME="${RAWFILE_ROOT}.sqlite"
SUMMARY_FILE_NAME="${RAWFILE_ROOT}.summary.sqlite"
runalyzer-gather ${SUMMARY_FILE_NAME} ${RAWFILE_NAME}
STARTUP_TIME=$(runalyzer -m ${SUMMARY_FILE_NAME} -c 'print(q("select $t_init.max").fetchall()[0][0])' | grep -v INFO)                                          
FIRST_STEP=$(runalyzer -m ${SUMMARY_FILE_NAME} -c 'print(sum(p[0] for p in q("select $t_step.max").fetchall()[0:1]))' | grep -v INFO)
FIRST_10_STEPS=$(runalyzer -m ${SUMMARY_FILE_NAME} -c 'print(sum(p[0] for p in q("select $t_step.max").fetchall()[0:10]))' | grep -v INFO)
SECOND_10_STEPS=$(runalyzer -m ${SUMMARY_FILE_NAME} -c 'print(sum(p[0] for p in q("select $t_step.max").fetchall()[10:19]))' | grep -v INFO)
printf "==== ${rawfile_name} -> ${SUMMARY_FILE_NAME} ====\n"
printf "STARTUP:     ${STARTUP_TIME}\n"
printf "FIRST_STEP:  ${FIRST_STEP}\n"
printf "2nd 9 STEPS: ${SECOND_10_STEPS}\n"

