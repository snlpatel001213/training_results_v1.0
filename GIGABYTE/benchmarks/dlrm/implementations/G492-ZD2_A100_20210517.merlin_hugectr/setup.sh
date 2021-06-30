### gigabyte_g492.json

{
  "solver": {
    "lr_policy": "fixed",
    "display": 1000,
    "max_iter": 75868,
    "gpu": [0,1,2,3,4,5,6,7],
    "batchsize": 55296,
    "batchsize_eval": 1769472,
    "eval_batches": 51,
    "snapshot": 10000000,
    "snapshot_prefix": "./",
    "eval_interval": 3790,
    "mixed_precision": 1024,
    "eval_metrics": ["AUC:0.8025"],
    "enable_overlap": true,
    "holistic_cuda_graph": true
  },

  "optimizer": {
    "type": "SGD",
    "global_update": false,
    "sgd_hparam": {
        "learning_rate": 24.0,
        "atomic_update": true,
        "warmup_steps": 2750,
        "decay_start": 49315,
        "decay_steps": 27772,
        "decay_power": 2.0,
        "end_lr": 0.0
    }
  },
   "all_reduce": {
     "algo" : "Oneshot",
     "grouped" : false
   },
  "layers": [
    {
      "name": "data",
      "type": "Data",
      "format": "RawAsync",
      "async_param" : {
        "num_threads": 32,
        "num_batches_per_thread" : 4,
        "io_block_size": 552960,
        "io_depth" : 2,
        "io_alignment": 512,
        "shuffle": true
      },
      "num_samples": 4195196928,
      "slot_size_array": [39884406,    39043,    17289,     7420,    20263,    3,  7120,     1543,  63, 38532951,  2953546,   403346, 10,     2208,    11938,      155,        4,      976, 14, 39979771, 25641295, 39664984,   585935,    12972,  108,  36],
      "source": "/raid/datasets/criteo/mlperf/40m.limit_preshuffled/train_data.bin",
      "eval_num_samples": 89137319,
      "eval_source": "/raid/datasets/criteo/mlperf/40m.limit_preshuffled/test_data.bin",
      "check": "None",
      "cache_eval_data": 51,
      "label": {
        "top": "label",
        "label_dim": 1
      },
      "dense": {
        "top": "dense",
        "dense_dim": 13,
        "aligned": "Auto"
      },
      "sparse": [
        {
          "top": "data1",
          "type": "DistributedSlot",
          "max_feature_num_per_sample": 26,
          "max_nnz": 1,
          "slot_num": 26
        }
      ]
    },
    {
      "name": "sparse_embedding1",
      "type": "HybridSparseEmbedding",
      "bottom": "data1",
      "top": "sparse_embedding1",
      "sparse_embedding_hparam": {
        "slot_size_array": [39884406,    39043,    17289,     7420,    20263,    3,  7120,     1543,  63, 38532951,  2953546,   403346, 10,     2208,    11938,      155,        4,      976, 14, 39979771, 25641295, 39664984,   585935,    12972,  108,  36],
        "embedding_vec_size": 128,
        "combiner": 0,
        "max_num_frequent_categories": 2,
        "communication_type" : "NVLink_SingleNode"
      }
    },
    {
      "name": "fc1",
      "type": "FusedInnerProduct",
      "position": "Head",
      "bottom": "dense",
      "top": ["fc11","fc12", "fc13", "fc14"],
      "fc_param": {
        "num_output": 512
      }
    },

    {
      "name": "fc2",
      "type": "FusedInnerProduct",
      "position": "Body",
      "bottom": ["fc11","fc12", "fc13", "fc14"],
      "top": ["fc21","fc22", "fc23", "fc24"],
      "fc_param": {
        "num_output": 256
      }
    },


    {
      "name": "fc3",
      "type": "FusedInnerProduct",
      "position": "Tail",
      "bottom": ["fc21","fc22", "fc23", "fc24"],
      "top": "fc3",
      "fc_param": {
        "num_output": 128
      }
    },

    {
      "name": "interaction1",
      "type": "Interaction",
      "bottom": ["fc3", "sparse_embedding1"],
      "top": "interaction1"
    },

    {
      "name": "fc4",
      "type": "FusedInnerProduct",
      "bottom": "interaction1",
      "position": "Head",
      "top": ["fc41","fc42", "fc43", "fc44"],
       "fc_param": {
        "num_output": 1024
      }
    },

    {
      "name": "fc5",
      "type": "FusedInnerProduct",
      "position": "Body",
      "bottom": ["fc41","fc42", "fc43", "fc44"],
      "top": ["fc51","fc52", "fc53", "fc54"],
      "fc_param": {
        "num_output": 1024
      }
    },

    {
      "name": "fc6",
      "type": "FusedInnerProduct",
      "position": "Body",
      "bottom": ["fc51","fc52", "fc53", "fc54"],
      "top": ["fc61","fc62", "fc63", "fc64"],
      "fc_param": {
        "num_output": 512
      }
    },

    {
      "name": "fc7",
      "type": "FusedInnerProduct",
      "position": "Body",
      "bottom": ["fc61","fc62", "fc63", "fc64"],
      "top": ["fc71","fc72","fc73","fc74"],
      "fc_param": {
        "num_output": 256
      }
    },

    {
      "name": "fc8",
      "type": "FusedInnerProduct",
      "position": "Tail",
      "activation": "None",
      "bottom": ["fc71","fc72","fc73","fc74"],
      "top": "fc8",
      "fc_param": {
        "num_output": 1
      }
    },

    {
      "name": "loss",
      "type": "BinaryCrossEntropyLoss",
      "bottom": ["fc8","label"],
      "top": "loss"
    }
  ]
}


### config_gigabyte.sh

## DL params
export BATCH_SIZE=55296
export DGXNGPU=8

export CONFIG="gigabyte_g492.json"

## System run parms
export DGXNNODES=1
export DGXSYSTEM=$(basename $(readlink -f ${BASH_SOURCE[0]}) | sed 's/^config_//' | sed 's/\.sh$//' )
export WALLTIME=00:10:00
export OMPI_MCA_btl="^openib"
export MOUNTS=/raid:/raid

export SBATCH_NETWORK=""


