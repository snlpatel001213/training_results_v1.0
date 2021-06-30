## DL params
export BATCH_SIZE=55296
export DGXNGPU=8

export CONFIG="dgx_a100_8x8x864.json"

## System run parms
export DGXNNODES=8
export DGXSYSTEM=$(basename $(readlink -f ${BASH_SOURCE[0]}) | sed 's/^config_//' | sed 's/\.sh$//' )
export WALLTIME=00:15:00
export OMPI_MCA_btl="^openib"
export MOUNTS=/raid:/raid

export SBATCH_NETWORK=sharp