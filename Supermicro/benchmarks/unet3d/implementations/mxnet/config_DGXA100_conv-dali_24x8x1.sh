#source $(dirname ${BASH_SOURCE[0]})/config_DGXA100_common.sh

## DL params
export OPTIMIZER="nag"
export BATCH_SIZE="1"
export VAL_BATCH_SIZE="1"
export LR="1.5"
export LR_WARMUP_EPOCHS="1000"
export MAX_EPOCHS=${MAX_EPOCHS:-7778}
export START_EVAL_AT=778
export EVALUATE_EVERY=16
export QUALITY_THRESHOLD="0.908"
export INPUT_BATCH_MULTIPLIER=4
export NUM_WORKERS=4
export ASYNC_PARAMS=" --nodes_for_eval 6 -sgs 2"
export EXTRA_PARAMS=${EXTRA_PARAMS:-""}
export TARGET_DIR=${TARGET_DIR:-""}

export SBATCH_NETWORK=sharp
#export MXNET_EXEC_ENABLE_ADDTO=1
export NCCL_SHARP_GROUP_SIZE_THRESH=7
export OMP_NUM_THREADS=1
export HOROVOD_CYCLE_TIME=0.1
#export MXNET_HOROVOD_NUM_GROUPS=20
export OMPI_MCA_btl=^openib
#export NCCL_MAX_RINGS=8
#export NCCL_BUFFSIZE=2097152
#export NCCL_NET_GDR_READ=1
#export HOROVOD_FUSION_THRESHOLD=67108864
#export HOROVOD_NUM_NCCL_STREAMS=1
#export HOROVOD_BATCH_D2D_MEMCOPIES=1
#export HOROVOD_GROUPED_ALLREDUCES=1

## System run parms
export DGXNNODES=24
export DGXSYSTEM=$(basename $(readlink -f ${BASH_SOURCE[0]}) | sed 's/^config_//' | sed 's/\.sh$//' )
WALLTIME_MINUTES=60
export WALLTIME=$((${NEXP} * ${WALLTIME_MINUTES}))

## System config params
export DGXNGPU=8
export DGXSOCKETCORES=64
export DGXNSOCKET=2
export DGXHT=2  # HT is on is 2, HT off is 1