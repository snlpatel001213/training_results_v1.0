python3 mask_rcnn_main.py --nobinarylog --${INTERNAL}_job_name=coordinator --${INTERNAL}_jobs="tpu_worker|${INTERNAL_PATH} --${INTERNAL}_num_eigen_threads=16 --${INTERNAL}_num_operation_threads=16 --${INTERNAL}_port=14001 --${INTERNAL}_rpc_layer=rpc2 --${INTERNAL}_task=0 --census_cpu_accounting_enabled --noenable_profiling --eval_batch_size=256 --gfs_user=tpu-perf-team --hparams=first_lr_drop_step=5625,second_lr_drop_step=7500,lr_warmup_step=1800,learning_rate=0.24,shuffle_buffer_size=4096,transpose_img_dimensions_last=true --init_dummy_file=${INTERNAL_PATH} --master=${INTERNAL_PATH} --model_dir=${INTERNAL_PATH} --num_epochs=20 --num_shards=64 --replicas_per_host=2 --resnet_checkpoint=${INTERNAL_PATH} --rpclog=-1 --sleep_after_init=300 --train_batch_size=256 --training_file_pattern="${INTERNAL_PATH} --val_json_file=${INTERNAL_PATH} --validation_file_pattern="${INTERNAL_PATH}