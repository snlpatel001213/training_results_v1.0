# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Contains utility and supporting functions for ResNet.

  This module contains ResNet code which does not directly build layers. This
includes dataset management, hyperparameter and optimizer code, and argument
parsing. Code for defining the ResNet layers can be found in resnet_model.py.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import argparse
import os

import tensorflow as tf  # pylint: disable=g-bad-import-order

from mlperf_compliance import mlperf_log
from mlperf_logging import mllog
from mlperf_compliance import tf_mlperf_log
from mlperf_resnet import resnet_model
from mlperf_utils.arg_parsers import parsers
from mlperf_utils.export import export
from mlperf_utils.logs import hooks_helper
from mlperf_utils.logs import logger
from mlperf_utils.misc import model_helpers

global is_mpi
try:
    import horovod.tensorflow as hvd
    hvd.init()
    is_mpi = hvd.size()
except ImportError:
    is_mpi = 0
    print("No MPI horovod support, this is running in no-MPI mode!")

mllogger = mllog.get_mllogger()
filenames = "resnet50v1.5.log-" + str(hvd.rank())
mllog.config(filename=filenames)
workername = "worker" + str(hvd.rank())
mllog.config(
    default_namespace = workername,
    default_stack_offset = 1,
    default_clear_line = False,
    root_dir = os.path.normpath(
      os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..")))
mllogger.event(key=mllog.constants.CACHE_CLEAR)
mllogger.start(key=mllog.constants.RUN_START)

_NUM_EXAMPLES_NAME = "num_examples"
_NUM_IMAGES = {
        'train': 1281167,
        'validation': 50000
}


################################################################################
# Functions for input processing.
################################################################################
def process_record_dataset(dataset, is_training, batch_size, shuffle_buffer,
                           parse_record_fn, num_epochs=1, num_gpus=None,
                           examples_per_epoch=None, dtype=tf.float32):
  """Given a Dataset with raw records, return an iterator over the records.

  Args:
    dataset: A Dataset representing raw records
    is_training: A boolean denoting whether the input is for training.
    batch_size: The number of samples per batch.
    shuffle_buffer: The buffer size to use when shuffling records. A larger
      value results in better randomness, but smaller values reduce startup
      time and use less memory.
    parse_record_fn: A function that takes a raw record and returns the
      corresponding (image, label) pair.
    num_epochs: The number of epochs to repeat the dataset.
    num_gpus: The number of gpus used for training.
    examples_per_epoch: The number of examples in an epoch.
    dtype: Data type to use for images/features.

  Returns:
    Dataset of (image, label) pairs ready for iteration.
  """

  # We prefetch a batch at a time, This can help smooth out the time taken to
  # load input files as we go through shuffling and processing.
  dataset = dataset.prefetch(buffer_size=batch_size)
  if is_training:
    if is_mpi:
      dataset = dataset.shard(hvd.size(), hvd.rank())
    # Shuffle the records. Note that we shuffle before repeating to ensure
    # that the shuffling respects epoch boundaries.
    dataset = dataset.shuffle(buffer_size=shuffle_buffer)

  # If we are training over multiple epochs before evaluating, repeat the
  # dataset for the appropriate number of epochs.
  dataset = dataset.repeat(num_epochs)

  # Parse the raw records into images and labels. Testing has shown that setting
  # num_parallel_batches > 1 produces no improvement in throughput, since
  # batch_size is almost always much greater than the number of CPU cores.
  dataset = dataset.apply(
      tf.data.experimental.map_and_batch(
          lambda value: parse_record_fn(value, is_training, dtype),
          batch_size=batch_size,
          num_parallel_batches=1))

  # Operations between the final prefetch and the get_next call to the iterator
  # will happen synchronously during run time. We prefetch here again to
  # background all of the above processing work and keep it out of the
  # critical training path. Setting buffer_size to tf.contrib.data.AUTOTUNE
  # allows DistributionStrategies to adjust how many batches to fetch based
  # on how many devices are present.
  dataset = dataset.prefetch(buffer_size=tf.data.experimental.AUTOTUNE)

  return dataset


def get_synth_input_fn(height, width, num_channels, num_classes):
  """Returns an input function that returns a dataset with zeroes.

  This is useful in debugging input pipeline performance, as it removes all
  elements of file reading and image preprocessing.

  Args:
    height: Integer height that will be used to create a fake image tensor.
    width: Integer width that will be used to create a fake image tensor.
    num_channels: Integer depth that will be used to create a fake image tensor.
    num_classes: Number of classes that should be represented in the fake labels
      tensor

  Returns:
    An input_fn that can be used in place of a real one to return a dataset
    that can be used for iteration.
  """
  def input_fn(is_training, data_dir, batch_size, *args, **kwargs):  # pylint: disable=unused-argument
    images = tf.zeros((batch_size, height, width, num_channels), tf.float32)
    labels = tf.zeros((batch_size, num_classes), tf.int32)
    return tf.data.Dataset.from_tensors((images, labels)).repeat()

  return input_fn


################################################################################
# Functions for running training/eval/validation loops for the model.
################################################################################
def learning_rate_with_decay(
    batch_size, batch_denom, num_images, boundary_epochs, decay_rates,
    base_lr=0.1, enable_lars=False):
  """Get a learning rate that decays step-wise as training progresses.

  Args:
    batch_size: the number of examples processed in each training batch.
    batch_denom: this value will be used to scale the base learning rate.
      `0.1 * batch size` is divided by this number, such that when
      batch_denom == batch_size, the initial learning rate will be 0.1.
    num_images: total number of images that will be used for training.
    boundary_epochs: list of ints representing the epochs at which we
      decay the learning rate.
    decay_rates: list of floats representing the decay rates to be used
      for scaling the learning rate. It should have one more element
      than `boundary_epochs`, and all elements should have the same type.
    base_lr: Initial learning rate scaled based on batch_denom.

  Returns:
    Returns a function that takes a single argument - the number of batches
    trained so far (global_step)- and returns the learning rate to be used
    for training the next batch.
  """
  initial_learning_rate = base_lr * batch_size / batch_denom
  batches_per_epoch = num_images / batch_size

  # Multiply the learning rate by 0.1 at 100, 150, and 200 epochs.
  boundaries = [int(batches_per_epoch * epoch) for epoch in boundary_epochs]
  vals = [initial_learning_rate * decay for decay in decay_rates]

  def learning_rate_fn(global_step):
    lr = tf.compat.v1.train.piecewise_constant(global_step, boundaries, vals)
    warmup_steps = int(batches_per_epoch * 5)
    warmup_lr = (
        initial_learning_rate * tf.cast(global_step, tf.float32) / tf.cast(
        warmup_steps, tf.float32))
    return tf.cond(pred=global_step < warmup_steps, true_fn=lambda: warmup_lr, false_fn=lambda: lr)

  def poly_rate_fn(global_step):
    """Handles linear scaling rule, gradual warmup, and LR decay.

    The learning rate starts at 0, then it increases linearly per step.  After
    flags.poly_warmup_epochs, we reach the base learning rate (scaled to account
    for batch size). The learning rate is then decayed using a polynomial rate
    decay schedule with power 2.0.

    Args:
    global_step: the current global_step

    Returns:
    returns the current learning rate
    """

    # Learning rate schedule for LARS polynomial schedule
    if batch_size <= 4096:
      plr = 10.0
      w_epochs = 5
    elif batch_size <= 8192:
      plr = 10.0
      w_epochs = 5
    elif batch_size <= 16384:
      plr = 25.0
      w_epochs = 5
    else: # e.g. 32768
      plr = 33.0
      w_epochs = 25

    # overwrite plr
    # Note: the following may need to be changed when changing HPs
    # Applying Google v0.7 tpu-v3-32-TF2.0 HyperParameters
    # Apply NVIDIA HP
    plr = 10.5
    w_epochs = 2
    #w_steps = int(w_epochs * batches_per_epoch)
    # 313 per step, warmup 2 epochs
    # 393 per step
    w_steps = 786 
    wrate = (plr * tf.cast(global_step, tf.float32) / tf.cast(
        w_steps, tf.float32))

    num_epochs = 37  # not used 
    #train_steps = batches_per_epoch * num_epochs
    #train_steps = 12794 # Google learning rate decay step + 626 -1
    train_steps = 14541
    mllogger.event(key=mllog.constants.LARS_OPT_LR_DECAY_STEPS, value=train_steps-w_steps+1)

    min_step = tf.constant(1, dtype=tf.int64)
    decay_steps = tf.maximum(min_step, tf.subtract(global_step, w_steps))
    poly_rate = tf.compat.v1.train.polynomial_decay(
        plr,
        decay_steps,
        train_steps - w_steps + 1,
        power=2.0)
    mllogger.event(key=mllog.constants.OPT_BASE_LR, value=plr)
    mllogger.event(key=mllog.constants.LARS_OPT_LR_DECAY_POLY_POWER, value=2)
    mllogger.event(key=mllog.constants.LARS_OPT_END_LR, value=0.0001)
    mllogger.event(key=mllog.constants.OPT_LR_WARMUP_EPOCHS, value=w_epochs)
    return tf.compat.v1.where(global_step <= w_steps, wrate, poly_rate)

  # For LARS we have a new learning rate schedule
  if enable_lars:
    return poly_rate_fn

  return learning_rate_fn


def resnet_model_fn(features, labels, mode, model_class,
                    resnet_size, weight_decay, learning_rate_fn, momentum,
                    data_format, version, loss_scale, loss_filter_fn=None,
                    dtype=resnet_model.DEFAULT_DTYPE,
                    label_smoothing=0.0, enable_lars=False,
                    use_bfloat16=False):
  """Shared functionality for different resnet model_fns.

  Initializes the ResnetModel representing the model layers
  and uses that model to build the necessary EstimatorSpecs for
  the `mode` in question. For training, this means building losses,
  the optimizer, and the train op that get passed into the EstimatorSpec.
  For evaluation and prediction, the EstimatorSpec is returned without
  a train op, but with the necessary parameters for the given mode.

  Args:
    features: tensor representing input images
    labels: tensor representing class labels for all input images
    mode: current estimator mode; should be one of
      `tf.estimator.ModeKeys.TRAIN`, `EVALUATE`, `PREDICT`
    model_class: a class representing a TensorFlow model that has a __call__
      function. We assume here that this is a subclass of ResnetModel.
    resnet_size: A single integer for the size of the ResNet model.
    weight_decay: weight decay loss rate used to regularize learned variables.
    learning_rate_fn: function that returns the current learning rate given
      the current global_step
    momentum: momentum term used for optimization
    data_format: Input format ('channels_last', 'channels_first', or None).
      If set to None, the format is dependent on whether a GPU is available.
    version: Integer representing which version of the ResNet network to use.
      See README for details. Valid values: [1, 2]
    loss_scale: The factor to scale the loss for numerical stability. A detailed
      summary is present in the arg parser help text.
    loss_filter_fn: function that takes a string variable name and returns
      True if the var should be included in loss calculation, and False
      otherwise. If None, batch_normalization variables will be excluded
      from the loss.
    dtype: the TensorFlow dtype to use for calculations.
    use_bfloat16: Whether to use bfloat16 type for calculations.

  Returns:
    EstimatorSpec parameterized according to the input params and the
    current mode.
  """

  # Generate a summary node for the images
  tf.compat.v1.summary.image('images', features, max_outputs=6)

  # Checks that features/images have same data type being used for calculations.
  assert features.dtype == dtype

  if use_bfloat16 == True:
    dtype = tf.bfloat16

  features = tf.cast(features, dtype)

  model = model_class(resnet_size, data_format, version=version, dtype=dtype)

  logits = model(features, mode == tf.estimator.ModeKeys.TRAIN)

  # This acts as a no-op if the logits are already in fp32 (provided logits are
  # not a SparseTensor). If dtype is is low precision, logits must be cast to
  # fp32 for numerical stability.
  logits = tf.cast(logits, tf.float32)

  num_examples_metric = tf_mlperf_log.sum_metric(tensor=tf.shape(input=logits)[0], name=_NUM_EXAMPLES_NAME)

  predictions = {
      'classes': tf.argmax(input=logits, axis=1),
      'probabilities': tf.nn.softmax(logits, name='softmax_tensor')
  }


  if mode == tf.estimator.ModeKeys.PREDICT:
    # Return the predictions and the specification for serving a SavedModel
    return tf.estimator.EstimatorSpec(
        mode=mode,
        predictions=predictions,
        export_outputs={
            'predict': tf.estimator.export.PredictOutput(predictions)
        })

  # Calculate loss, which includes softmax cross entropy and L2 regularization.

  if label_smoothing != 0.0:
    one_hot_labels = tf.one_hot(labels, 1001)
    cross_entropy = tf.compat.v1.losses.softmax_cross_entropy(
        logits=logits, onehot_labels=one_hot_labels,
        label_smoothing=label_smoothing)
  else:
    cross_entropy = tf.compat.v1.losses.sparse_softmax_cross_entropy(
        logits=logits, labels=labels)

  # Create a tensor named cross_entropy for logging purposes.
  tf.identity(cross_entropy, name='cross_entropy')
  tf.compat.v1.summary.scalar('cross_entropy', cross_entropy)

  # If no loss_filter_fn is passed, assume we want the default behavior,
  # which is that batch_normalization variables are excluded from loss.
  def exclude_batch_norm(name):
    return 'batch_normalization' not in name
  loss_filter_fn = loss_filter_fn or exclude_batch_norm


  # Add weight decay to the loss.
  l2_loss = weight_decay * tf.add_n(
      # loss is computed using fp32 for numerical stability.
      [tf.nn.l2_loss(tf.cast(v, tf.float32)) for v in tf.compat.v1.trainable_variables()
       if loss_filter_fn(v.name)])
  tf.compat.v1.summary.scalar('l2_loss', l2_loss)
  loss = cross_entropy + l2_loss

  if mode == tf.estimator.ModeKeys.TRAIN:
    global_step = tf.compat.v1.train.get_or_create_global_step()

    learning_rate = learning_rate_fn(global_step)

    log_id = mlperf_log.resnet_print(key=mlperf_log.OPT_LR, deferred=True)
    learning_rate = tf_mlperf_log.log_deferred(op=learning_rate, log_id=log_id,
                                               every_n=100)

    # Create a tensor named learning_rate for logging purposes
    tf.identity(learning_rate, name='learning_rate')
    tf.compat.v1.summary.scalar('learning_rate', learning_rate)


    if enable_lars:
      optimizer = tf.compat.v1.train.LARSOptimizer(
          learning_rate=learning_rate,
          momentum=momentum,
          weight_decay=weight_decay,
          skip_list=['batch_normalization', 'bias'])
      mllogger.event(key=mllog.constants.OPT_NAME,
                            value=mllog.constants.LARS)
      mllogger.event(key=mllog.constants.LARS_EPSILON, value=0.0)
      mllogger.event(key=mllog.constants.LARS_OPT_WEIGHT_DECAY, value=weight_decay)
    else:
      optimizer = tf.compat.v1.train.MomentumOptimizer(
          learning_rate=learning_rate,
          momentum=momentum
      )
    if is_mpi:
      optimizer = hvd.DistributedOptimizer(optimizer)

    if loss_scale != 1:
      # When computing fp16 gradients, often intermediate tensor values are
      # so small, they underflow to 0. To avoid this, we multiply the loss by
      # loss_scale to make these tensor values loss_scale times bigger.
      scaled_grad_vars = optimizer.compute_gradients(loss * loss_scale)

      # Once the gradient computation is complete we can scale the gradients
      # back to the correct scale before passing them to the optimizer.
      unscaled_grad_vars = [(grad / loss_scale, var)
                            for grad, var in scaled_grad_vars]
      minimize_op = optimizer.apply_gradients(unscaled_grad_vars, global_step)
    else:
      minimize_op = optimizer.minimize(loss, global_step)

    update_ops = tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.UPDATE_OPS)
    train_op = tf.group(minimize_op, update_ops, num_examples_metric[1])
  else:
    train_op = None

  accuracy = tf.compat.v1.metrics.accuracy(labels, predictions['classes'])
  accuracy_top_5 = tf.compat.v1.metrics.mean(tf.nn.in_top_k(predictions=logits,
                                                  targets=labels,
                                                  k=5,
                                                  name='top_5_op'))

  metrics = {'accuracy': accuracy,
             'accuracy_top_5': accuracy_top_5,
             _NUM_EXAMPLES_NAME: num_examples_metric}

  # Create a tensor named train_accuracy for logging purposes
  tf.identity(accuracy[1], name='train_accuracy')
  tf.identity(accuracy_top_5[1], name='train_accuracy_top_5')
  tf.compat.v1.summary.scalar('train_accuracy', accuracy[1])
  tf.compat.v1.summary.scalar('train_accuracy_top_5', accuracy_top_5[1])

  return tf.estimator.EstimatorSpec(
      mode=mode,
      predictions=predictions,
      loss=loss,
      train_op=train_op,
      eval_metric_ops=metrics)


def per_device_batch_size(batch_size, num_gpus):
  """For multi-gpu, batch-size must be a multiple of the number of GPUs.

  Note that this should eventually be handled by DistributionStrategies
  directly. Multi-GPU support is currently experimental, however,
  so doing the work here until that feature is in place.

  Args:
    batch_size: Global batch size to be divided among devices. This should be
      equal to num_gpus times the single-GPU batch_size for multi-gpu training.
    num_gpus: How many GPUs are used with DistributionStrategies.

  Returns:
    Batch size per device.

  Raises:
    ValueError: if batch_size is not divisible by number of devices
  """
  if num_gpus <= 1:
    return batch_size

  remainder = batch_size % num_gpus
  if remainder:
    err = ('When running with multiple GPUs, batch size '
           'must be a multiple of the number of available GPUs. Found {} '
           'GPUs with a batch size of {}; try --batch_size={} instead.'
          ).format(num_gpus, batch_size, batch_size - remainder)
    raise ValueError(err)
  return int(batch_size / num_gpus)


def resnet_main(seed, flags, model_function, input_function, shape=None):
  """Shared main loop for ResNet Models.

  Args:
    flags: FLAGS object that contains the params for running. See
      ResnetArgParser for created flags.
    model_function: the function that instantiates the Model and builds the
      ops for train/eval. This will be passed directly into the estimator.
    input_function: the function that processes the dataset and returns a
      dataset that the estimator can train on. This will be wrapped with
      all the relevant flags for running and passed to estimator.
    shape: list of ints representing the shape of the images used for training.
      This is only used if flags.export_dir is passed.
  """


  # Using the Winograd non-fused algorithms provides a small performance boost.
  os.environ['TF_ENABLE_WINOGRAD_NONFUSED'] = '1'

  # Create session config based on values of inter_op_parallelism_threads and
  # intra_op_parallelism_threads. Note that we default to having
  # allow_soft_placement = True, which is required for multi-GPU and not
  # harmful for other modes.
  session_config = tf.compat.v1.ConfigProto(
      inter_op_parallelism_threads=flags.inter_op_parallelism_threads,
      intra_op_parallelism_threads=flags.intra_op_parallelism_threads,
      allow_soft_placement=True)

  if flags.num_gpus == 0:
    distribution = tf.distribute.OneDeviceStrategy('device:CPU:0')
  elif flags.num_gpus == 1:
    distribution = tf.distribute.OneDeviceStrategy('device:GPU:0')
  else:
    distribution = tf.distribute.MirroredStrategy(
        num_gpus=flags.num_gpus
    )

  mllogger.event(key=mllog.constants.SEED, value=seed)
  run_config = tf.estimator.RunConfig(train_distribute=distribution,
                                      session_config=session_config,
                                      log_step_count_steps=20, # output logs more frequently
                                      save_checkpoints_steps=2502,
                                      keep_checkpoint_max=1,
                                      tf_random_seed=seed)

  mllogger.event(key=mllog.constants.GLOBAL_BATCH_SIZE,
                          value=flags.batch_size*hvd.size())

  if is_mpi:
      if hvd.rank() == 0:
          model_dir = os.path.join(flags.model_dir,"main")
      else:
          model_dir = os.path.join(flags.model_dir,"tmp{}".format(hvd.rank()))
      benchmark_log_dir = flags.benchmark_log_dir if hvd.rank() == 0 else None
  else:
      model_dir = flags.model_dir
      benchmark_log_dir = flags.benchmark_log_dir

  classifier = tf.estimator.Estimator(
      model_fn=model_function, model_dir=model_dir, config=run_config,
      params={
          'resnet_size': flags.resnet_size,
          'data_format': flags.data_format,
          'batch_size': flags.batch_size,
          'version': flags.version,
          'loss_scale': flags.loss_scale,
          'dtype': flags.dtype,
          'label_smoothing': flags.label_smoothing,
          'enable_lars': flags.enable_lars,
          'weight_decay': flags.weight_decay,
          'fine_tune': flags.fine_tune,
          'use_bfloat16': flags.use_bfloat16
      })
  eval_classifier = tf.estimator.Estimator(
      model_fn=model_function, model_dir=model_dir.rsplit('/', 1)[0]+'/main', config=run_config,
      params={
          'resnet_size': flags.resnet_size,
          'data_format': flags.data_format,
          'batch_size': flags.batch_size,
          'version': flags.version,
          'loss_scale': flags.loss_scale,
          'dtype': flags.dtype,
          'label_smoothing': flags.label_smoothing,
          'enable_lars': flags.enable_lars,
          'weight_decay': flags.weight_decay,
          'fine_tune': flags.fine_tune,
          'use_bfloat16': flags.use_bfloat16
      })

  if benchmark_log_dir is not None:
    benchmark_logger = logger.BenchmarkLogger(benchmark_log_dir)
    benchmark_logger.log_run_info('resnet')
  else:
    benchmark_logger = None

  # for MPI only to figure out the steps per epoch or per eval, per worker 
  if is_mpi:
    num_eval_steps = _NUM_IMAGES['validation'] // flags.batch_size
    steps_per_epoch = _NUM_IMAGES['train'] // flags.batch_size
    steps_per_epoch_per_worker = steps_per_epoch // hvd.size()
    steps_per_eval_per_worker = steps_per_epoch_per_worker * flags.epochs_between_evals

  # The reference performs the first evaluation on the fourth epoch. (offset
  # eval by 3 epochs)
  success = False
  for i in range(flags.train_epochs // flags.epochs_between_evals):
    # Data for epochs_between_evals (i.e. 4 epochs between evals) worth of
    # epochs is concatenated and run as a single block inside a session. For
    # this reason we declare all of the epochs that will be run at the start.
    # Submitters may report in a way which is reasonable for their control flow.
    mllogger.start(key=mllog.constants.BLOCK_START, value=i+1)
    mllogger.event(key=mllog.constants.FIRST_EPOCH_NUM, value=i*flags.epochs_between_evals)
    mllogger.event(key=mllog.constants.EPOCH_COUNT, value=flags.epochs_between_evals)

    for j in range(flags.epochs_between_evals):
      mllogger.event(key=mllog.constants.EPOCH_NUM,
                              value=i * flags.epochs_between_evals + j)

    flags.hooks += ["examplespersecondhook"]
    if is_mpi:
      train_hooks = [hvd.BroadcastGlobalVariablesHook(0)]
      train_hooks = train_hooks + hooks_helper.get_train_hooks(
          flags.hooks,
          batch_size=flags.batch_size*hvd.size(),
          benchmark_log_dir=flags.benchmark_log_dir)
    else:
      train_hooks = hooks_helper.get_train_hooks(
          flags.hooks,
          batch_size=flags.batch_size,
          benchmark_log_dir=flags.benchmark_log_dir)

    _log_cache = []
    def formatter(x):
      """Abuse side effects to get tensors out of the model_fn."""
      if _log_cache:
        _log_cache.pop()
      _log_cache.append(x.copy())
      return str(x)

    compliance_hook = tf.estimator.LoggingTensorHook(
      tensors={_NUM_EXAMPLES_NAME: _NUM_EXAMPLES_NAME},
      every_n_iter=int(1e10),
      at_end=True,
      formatter=formatter)

    print('Starting a training cycle.')

    def input_fn_train():
      return input_function(
          is_training=True,
          data_dir=flags.data_dir,
          batch_size=per_device_batch_size(flags.batch_size, flags.num_gpus),
          num_epochs=flags.epochs_between_evals,
          num_gpus=flags.num_gpus,
          dtype=flags.dtype
      )
    if is_mpi:
      # if max step is set, use max_step, not the steps_per_eval_per_worker
      # assuming max_train_steps is smaller than steps_per_eval_per_worker
      # Also assuming when -- steps is specified, the train epochs should
      # be set to be equal to epochs_between_evals so that the
      # range(flags.train_epochs // flags.epochs_between_evals) gets to be 1
      if (flags.max_train_steps) and (flags.max_train_steps < steps_per_eval_per_worker):
          train_steps = flags.max_train_steps
      else:
          train_steps = steps_per_eval_per_worker

      classifier.train(input_fn=input_fn_train, hooks=train_hooks + [compliance_hook],
              steps=train_steps)
    else:
      classifier.train(input_fn=input_fn_train, hooks=train_hooks + [compliance_hook], max_steps=flags.max_train_steps)

    #train_examples = int(_log_cache.pop()[_NUM_EXAMPLES_NAME])
    #mlperf_log.resnet_print(key=mlperf_log.INPUT_SIZE, value=train_examples)
    mllogger.end(key=mllog.constants.BLOCK_STOP, value=i+1)

    print('Starting to evaluate.')
    # Evaluate the model and print results
    def input_fn_eval():
      return input_function(
          is_training=False,
          data_dir=flags.data_dir,
          #batch_size=per_device_batch_size(flags.batch_size, flags.num_gpus),
          batch_size=100,
          num_epochs=1,
          dtype=flags.dtype
      )


    mllogger.start(key=mllog.constants.EVAL_START)
    # flags.max_train_steps is generally associated with testing and profiling.
    # As a result it is frequently called with synthetic data, which will
    # iterate forever. Passing steps=flags.max_train_steps allows the eval
    # (which is generally unimportant in those circumstances) to terminate.
    # Note that eval will run for max_train_steps each loop, regardless of the
    # global_step count.
    eval_hooks = [hvd.BroadcastGlobalVariablesHook(0)]
    eval_results = eval_classifier.evaluate(input_fn=input_fn_eval,
                                       steps=flags.max_train_steps, hooks=eval_hooks)
    eval_results_per_worker = eval_results['accuracy']
    allreduced_results = hvd.allreduce(eval_results_per_worker)
    mllogger.event(key=mllog.constants.EVAL_SAMPLES, value=int(eval_results[_NUM_EXAMPLES_NAME]))
    #mllogger.event(key=mllog.constants.EVAL_ACCURACY, value=float(eval_results['accuracy']))
    mllogger.event(key=mllog.constants.EVAL_ACCURACY, value=float(allreduced_results))
    mllogger.end(key=mllog.constants.EVAL_STOP)
    print(allreduced_results)

    if benchmark_logger:
      benchmark_logger.log_estimator_evaluation_result(eval_results)

    if model_helpers.past_stop_threshold(
        flags.stop_threshold, float(allreduced_results)):
      success = True
      break

  mllogger.event(key=mllog.constants.RUN_STOP, value={"success": success})
  mllogger.end(key=mllog.constants.RUN_STOP)


class ResnetArgParser(argparse.ArgumentParser):
  """Arguments for configuring and running a Resnet Model."""

  def __init__(self, resnet_size_choices=None):
    super(ResnetArgParser, self).__init__(parents=[
        parsers.BaseParser(multi_gpu=False),
        parsers.PerformanceParser(num_parallel_calls=False),
        parsers.ImageModelParser(),
        parsers.ExportParser(),
        parsers.BenchmarkParser(),
    ])

    self.add_argument(
        '--version', '-v', type=int, choices=[1, 2],
        default=resnet_model.DEFAULT_VERSION,
        help='Version of ResNet. (1 or 2) See README.md for details.'
    )

    self.add_argument(
        '--resnet_size', '-rs', type=int, default=50,
        choices=resnet_size_choices,
        help='[default: %(default)s] The size of the ResNet model to use.',
        metavar='<RS>' if resnet_size_choices is None else None
    )

    self.add_argument(
        '--use_bfloat16', action='store_true', default=False,
        help='Whether to use bfloat16 type for computations.'
    )

  def parse_args(self, args=None, namespace=None):
    args = super(ResnetArgParser, self).parse_args(
        args=args, namespace=namespace)

    # handle coupling between dtype and loss_scale
    parsers.parse_dtype_info(args)

    return args
