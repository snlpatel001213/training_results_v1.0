## System config params
export DGXNNODES=1
export DGXSYSTEM=$(basename $(readlink -f ${BASH_SOURCE[0]}) | sed 's/^config_//' | sed 's/\.sh$//' )
export DGXNGPU=8
export DGXSOCKETCORES=16
export DGXNSOCKET=2
export DGXHT=2         # HT is on is 2, HT off is 1

## Run specific params
export DATADIR="/raid/datasets/rnnt/LibriSpeech/"
export BATCHSIZE=128
export EVAL_BATCHSIZE=338
export GRAD_ACCUMULATION_STEPS=1
#export WALLTIME=04:00:00
export MAX_SYMBOL=300
export EPOCH=80
export DATA_CPU_THREADS=16

## Opt flag
export FUSE_RELU_DROPOUT=true
export MULTI_TENSOR_EMA=true
export BATCH_EVAL_MODE=cg_unroll_pipeline
export APEX_LOSS=fp16
export APEX_JOINT=pack
export AMP_LVL=2
export BUFFER_PREALLOC=true
export VECTORIZED_SA=true
export EMA_UPDATE_TYPE=fp16
export DIST_LAMB=true
export MULTILAYER_LSTM=false
export IN_MEM_FILE_LIST=true
export ENABLE_PREFETCH=true
export VECTORIZED_SAMPLER=true
export DIST_SAMPLER=true
export TOKENIZED_TRANSCRIPT=true
export EXTRA_MOUNTS='/lustre/fsw/mlperf-ci/tokenized/:/datasets/tokenized'
export TRAIN_MANIFESTS='/datasets/tokenized/librispeech-train-clean-100-wav-tokenized.json
                        /datasets/tokenized/librispeech-train-clean-360-wav-tokenized.json
                        /datasets/tokenized/librispeech-train-other-500-wav-tokenized.json'
export VAL_MANIFESTS='/datasets/tokenized/librispeech-dev-clean-wav-tokenized.json'
