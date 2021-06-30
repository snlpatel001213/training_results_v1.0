## DL params
export BATCHSIZE=8
export EXTRA_PARAMS='--lr-decay-epochs 60 75 --lr-warmup-epoch=26 --lr=0.0045703 --weight-decay=4e-5 --bn-group=2 --gradient-predivide-factor=8 --input-batch-multiplier=8'

## System run parms
export DGXNNODES=32
export DGXSYSTEM=$(basename $(readlink -f ${BASH_SOURCE[0]}) | sed 's/^config_//' | sed 's/\.sh$//' )
WALLTIME_MINUTES=20
export WALLTIME=$((${NEXP} * ${WALLTIME_MINUTES}))

## System config params
export DGXNGPU=8
export DGXSOCKETCORES=64
export DGXNSOCKET=2
export DGXHT=2  # HT is on is 2, HT off is 1
