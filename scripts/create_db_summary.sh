#!/bin/bash

RUN_LOG_FILE=${1}
SUMMARY_FILE_NAME=${2}

rm -f ${SUMMARY_FILE_NAME}
runalyzer-gather ${SUMMARY_FILE_NAME} ${RUN_LOG_FILE}
