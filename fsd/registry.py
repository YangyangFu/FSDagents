"""FSDAgents provides registry nodes to support using modules across
projects. Each node is a child of the root registry in MMEngine.

More details can be found at
https://mmengine.readthedocs.io/en/latest/tutorials/registry.html.
"""
from mmengine.registry import DATA_SAMPLERS as MMENGINE_DATA_SAMPLERS
from mmengine.registry import DATASETS as MMENGINE_DATASETS
from mmengine.registry import EVALUATOR as MMENGINE_EVALUATOR
from mmengine.registry import HOOKS as MMENGINE_HOOKS
from mmengine.registry import LOG_PROCESSORS as MMENGINE_LOG_PROCESSORS
from mmengine.registry import LOOPS as MMENGINE_LOOPS
from mmengine.registry import METRICS as MMENGINE_METRICS
from mmengine.registry import MODEL_WRAPPERS as MMENGINE_MODEL_WRAPPERS
from mmengine.registry import MODELS as MMENGINE_MODELS
from mmengine.registry import \
    OPTIM_WRAPPER_CONSTRUCTORS as MMENGINE_OPTIM_WRAPPER_CONSTRUCTORS
from mmengine.registry import OPTIM_WRAPPERS as MMENGINE_OPTIM_WRAPPERS
from mmengine.registry import OPTIMIZERS as MMENGINE_OPTIMIZERS
from mmengine.registry import PARAM_SCHEDULERS as MMENGINE_PARAM_SCHEDULERS
from mmengine.registry import \
    RUNNER_CONSTRUCTORS as MMENGINE_RUNNER_CONSTRUCTORS
from mmengine.registry import RUNNERS as MMENGINE_RUNNERS
from mmengine.registry import TASK_UTILS as MMENGINE_TASK_UTILS
from mmengine.registry import TRANSFORMS as MMENGINE_TRANSFORMS
from mmengine.registry import VISBACKENDS as MMENGINE_VISBACKENDS
from mmengine.registry import VISUALIZERS as MMENGINE_VISUALIZERS
from mmengine.registry import \
    WEIGHT_INITIALIZERS as MMENGINE_WEIGHT_INITIALIZERS
from mmengine.registry import Registry, count_registered_modules

# manging all kinds of modules inheriting from 'nn.Module'
DATA_SAMPLERS=Registry('data_sampler', 
                      parent=MMENGINE_DATA_SAMPLERS, 
                      locations=['fsd.datasets.samplers'])

MODELS = Registry('model', parent=MMENGINE_MODELS, locations=['fsd.models', 'fsd.agents'])
NECKS = MODELS 
BACKBONES = MODELS
HEADS = MODELS
TRANSFORMERS = MODELS

DATASETS = Registry(
    'dataset', parent=MMENGINE_DATASETS, locations=['fsd.datasets'])

TRANSFORMS = Registry(
    'transform', parent=MMENGINE_TRANSFORMS, locations=['fsd.datasets.transforms', 'fsd.agents'])

RUNNERS = Registry('runner', parent=MMENGINE_RUNNERS, locations=['fsd.runner'])

AGENTS = MODELS
AGENT_TRANSFORMS = TRANSFORMS

TASK_UTILS = Registry('task_util', parent=MMENGINE_TASK_UTILS, locations=['fsd.agents'])

VISUALIZERS = Registry('visualizer', parent=MMENGINE_VISUALIZERS, locations=['fsd.visualization'])

CONTROLLERS = Registry('controller', locations=['fsd.controllers'])

METRICS = Registry('metric', parent=MMENGINE_METRICS, locations=['fsd.evaluation.metrics'])

HOOKS = Registry('hook', parent=MMENGINE_HOOKS, locations=['fsd.hooks'])

#count_registered_modules()