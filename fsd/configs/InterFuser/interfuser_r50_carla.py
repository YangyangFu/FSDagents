_base_ = [
    '../_base_/default_runtime.py',
]

work_dir = '.'


# If point cloud range is changed, the models should also change their point
# cloud range accordingly
point_cloud_range = [-51.2, -51.2, -5.0, 51.2, 51.2, 3.0]
img_norm_cfg = dict(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225], to_rgb=True)
class_names = [
'car','van','truck','bicycle','traffic_sign','traffic_cone','traffic_light','pedestrian','others'
]
metainfo = dict(
    classes = class_names,
)

input_modality = dict(
    use_lidar=True, 
    use_camera=True, 
    use_radar=False, 
    use_map=False, 
    use_external=True
)

camera_sensors = [
    'CAM_FRONT', 
    'CAM_FRONT_LEFT', 
    'CAM_FRONT_RIGHT', 
    'CAM_FRONT', # load one more times
]
lidar_sensors = ['LIDAR_TOP']

EMBED_DIMS = 256
PLANNING_STEPS = 10

model = dict(
    type='InterFuser',
    num_queries=411,
    embed_dims=EMBED_DIMS,
    img_backbone=dict(
        type='mmpretrain.TIMMBackbone', #timm model wrapper
        model_name='resnet50d',
        features_only=True,
        pretrained=True,
        out_indices=[4]
    ),
    pts_backbone=dict(
        type='mmpretrain.TIMMBackbone', #timm model wrapper
        model_name='resnet18d',
        features_only=True,
        pretrained=True,
        out_indices=[4]
    ),
    img_neck=dict(
        type='Conv1d',
        in_channels=2048,
        out_channels=EMBED_DIMS
    ),
    pts_neck=dict(
        type='Conv1d',
        in_channels=512,
        out_channels=EMBED_DIMS
    ),
    encoder = dict( # DetrTransformerEncoder
        type='DETRLayerSequence',
        num_layers=6,
        layer_cfgs=dict(
            type='DETRLayer',
            attn_cfgs=dict( # MultiheadAttention
                type='MultiheadAttention',
                embed_dims=EMBED_DIMS,
                num_heads=8,
                attn_drop=0.,
                proj_drop=0.
            ),
            ffn_cfgs=dict(
                type='FFN',
                embed_dims=EMBED_DIMS,
                feedforward_channels=2048,
                num_fcs=2,
                ffn_drop=0.1,
                act_cfg=dict(type='ReLU', inplace=True)
            ),
            operation_order=['self_attn', 'norm', 'ffn', 'norm'],
            batch_first=False,
        )
    ),       
    decoder = dict(  # DetrTransformerDecoder
        type='DETRLayerSequence',
        num_layers=6,
        layer_cfgs=dict(
            type='DETRLayer',
            attn_cfgs=dict( # MultiheadAttention
                type='MultiheadAttention',
                embed_dims=EMBED_DIMS,
                num_heads=8,
                attn_drop=0.,
                proj_drop=0.,
            ),
            ffn_cfgs=dict(
                type='FFN',
                embed_dims=EMBED_DIMS,
                feedforward_channels=2048,
                num_fcs=2,
                ffn_drop=0.1,
                act_cfg=dict(type='ReLU', inplace=True)
            ),
            operation_order=['self_attn', 'norm', 'cross_attn', 'norm', 'ffn', 'norm'],
            batch_first=False,
        )
    ),
    heads=dict(
        type='interfuser_heads',
        num_waypoints_queries=PLANNING_STEPS,
        num_traffic_rule_queries=1,
        num_object_density_queries=400,
        waypoints_head=dict(
            type='interfuser_gru_waypoint',
            num_waypoints=10,
            input_size=EMBED_DIMS,
            hidden_size=64,
            num_layers=1,
            dropout=0.,
            batch_first=True, # yeah, original code use batch_first=True here
            loss_cfg=dict(
                type='MaskedSmoothL1Loss',
                beta=1.0,
                reduction='mean',
                loss_weight=1.0
            ),
            waypoints_weights=[
                0.1407441030399059,
                0.13352157985305926,
                0.12588535273178575,
                0.11775496498388233,
                0.10901991343009122,
                0.09952110967153563,
                0.08901438656870617,
                0.07708872007078788,
                0.06294267636589287,
                0.04450719328435308,
            ]),
        object_density_head=dict(
            type='interfuser_object_density',
            input_size=EMBED_DIMS + 32,
            hidden_size=64,
            output_size=7,
            loss_cfg=dict(
                type='L1Loss',
                _scope_='mmdet',
                reduction='mean',
                loss_weight=1.0
            )
        ),
        junction_head=dict(
            type='interfuser_traffic_rule',
            input_size=EMBED_DIMS,
            output_size=2,
            loss_cfg=dict(
                type='CrossEntropyLoss',
                _scope_='mmdet',
                use_sigmoid=True, # binary classification
                reduction='mean',
                loss_weight=1.0
            )
        ),
        stop_sign_head=dict(
            type='interfuser_traffic_rule',
            input_size=EMBED_DIMS,
            output_size=2,
            loss_cfg=dict(
                type='CrossEntropyLoss',
                _scope_='mmdet',
                use_sigmoid=True, # binary classification
                reduction='mean',
                loss_weight=1.0
            )
        ),
        traffic_light_head=dict(
            type='interfuser_traffic_rule',
            input_size=EMBED_DIMS,
            output_size=2,
            loss_cfg=dict(
                type='CrossEntropyLoss',
                _scope_='mmdet',
                use_sigmoid=True, # binary classification
                reduction='mean',
                loss_weight=1.0
            )
        )
    ),        
    positional_encoding=dict(
        num_feats=EMBED_DIMS//2,
        normalize=True
    ), 
    multi_view_encoding=dict(
        num_embeddings=5,
        embedding_dim=EMBED_DIMS
    ),
    data_preprocessor=dict(
        type="InterFuserDataPreprocessor")
)

dataset_type = "CarlaDataset"
data_root = "data/carla/" # v1
info_root = "data/carla/infos"
map_root = "data/carla/maps"
map_file = "data/carla/infos/b2d_map_infos.pkl"
file_client_args = dict(backend="disk")
ann_file_train=info_root + f"/b2d_infos_train.pkl"
ann_file_val=info_root + f"/b2d_infos_val.pkl"

train_pipeline = [
    dict(type="LoadMultiViewImageFromFiles", 
         channel_order = 'bgr', 
         to_float32=True
    ),
    dict(type="LoadPointsFromFileCarlaDataset", coord_type="LIDAR", load_dim=3, use_dim=[0, 1, 2]),
    dict(type="PhotoMetricDistortionMultiViewImage"),
    dict(type="InterFuserDensityMap", bev_range=[0, 20, -10, 10], pixels_per_meter=1),
    dict(
        type="LoadAnnotations3DPlanning",
        with_bbox_3d=True,
        with_label_3d=True,
        with_name_3d=True, # class names
        with_instances_ids=True,  # instance ids 
        with_instances_traj=True, # future
        with_ego_status=True, # ego status
        with_grids=True, # density map
    ),
    dict(type="ObjectRangeFilter", point_cloud_range=point_cloud_range),
    dict(type="ObjectNameFilter", classes=class_names),
    dict(type="ResizeMultiviewImage", target_size=[(341, 256), (195, 146), (195, 146), (900, 1600)]),
    dict(type="CenterCropMultiviewImage", crop_size=[(224, 224), (128, 128), (128, 128), (128, 128)]),
    dict(type="NormalizeMultiviewImage", 
        mean=img_norm_cfg['mean'], 
        std=img_norm_cfg['std'], 
        divider=255.0, 
        to_rgb=img_norm_cfg['to_rgb']
    ),
    dict(type="Collect3D", keys= []), # default keys are in xx_fields
    dict(type="DefaultFormatBundle3D")
]

train_dataloader = dict(
    batch_size = 16,
    num_workers = 1,
    dataset=dict(
        type=dataset_type,
        data_root=data_root,
        ann_file=ann_file_train,
        pipeline=train_pipeline,
        metainfo=metainfo,
        modality=input_modality,
        camera_sensors=camera_sensors,
        lidar_sensors=lidar_sensors,
        box_type_3d="LiDAR",
        filter_empty_gt = True,
        past_steps = 0, # past trajectory length
        prediction_steps = 0, # motion prediction length if any
        planning_steps = PLANNING_STEPS, # planning length
        sample_interval = 5, # sample interval # frames skiped per step
        test_mode = False
    ),
    sampler=dict(type="DefaultSampler", _scope_="mmengine", shuffle=True),
    pin_memory=True,
)

train_cfg = dict(
    type='EpochBasedTrainLoop', 
    max_epochs=25, 
    val_interval=1
)

# validataion
val_pipeline = [
    dict(type="LoadMultiViewImageFromFiles", 
         channel_order = 'bgr', 
         to_float32=True
    ),
    dict(type="LoadPointsFromFileCarlaDataset", coord_type="LIDAR", load_dim=3, use_dim=[0, 1, 2]),
    dict(type="PhotoMetricDistortionMultiViewImage"),
    dict(type="InterFuserDensityMap", bev_range=[0, 20, -10, 10], pixels_per_meter=1),
    dict(
        type="LoadAnnotations3DPlanning",
        with_bbox_3d=True,
        with_label_3d=True,
        with_name_3d=True, # class names
        with_instances_ids=True,  # instance ids 
        with_instances_traj=True, # future
        with_ego_status=True, # ego status
        with_grids=True, # density map
    ),
    dict(type="ObjectRangeFilter", point_cloud_range=point_cloud_range),
    dict(type="ObjectNameFilter", classes=class_names),
    dict(type="ResizeMultiviewImage", target_size=[(341, 256), (195, 146), (195, 146), (900, 1600)]),
    dict(type="CenterCropMultiviewImage", crop_size=[(224, 224), (128, 128), (128, 128), (128, 128)]),
    dict(type="NormalizeMultiviewImage", 
        mean=img_norm_cfg['mean'], 
        std=img_norm_cfg['std'], 
        divider=255.0, 
        to_rgb=img_norm_cfg['to_rgb']
    ),
    dict(type="Collect3D", keys= []), # default keys are in xx_fields
    dict(type="DefaultFormatBundle3D")
]


val_dataloader = dict(
    batch_size = 16,
    num_workers = 1,
    dataset=dict(
        type=dataset_type,
        data_root=data_root,
        ann_file=ann_file_val,
        pipeline=val_pipeline,
        metainfo=metainfo,
        modality=input_modality,
        camera_sensors=camera_sensors,
        lidar_sensors=lidar_sensors,
        box_type_3d="LiDAR",
        filter_empty_gt = True,
        past_steps = 0, # past trajectory length
        prediction_steps = 0, # motion prediction length if any
        planning_steps = PLANNING_STEPS, # planning length
        sample_interval = 5, # sample interval # frames skiped per step
        test_mode = True
    ),
    sampler=dict(type="DefaultSampler", _scope_="mmengine", shuffle=False),
    pin_memory=True,
)
val_evaluator = dict(type="TrajectoryMetric")
val_cfg = dict()

test_dataloader = val_dataloader
test_evaluator = val_evaluator
test_cfg = val_cfg

# optimizer
lr = 0.0005  # max learning rate
optim_wrapper = dict(
    type='OptimWrapper',
    _scope_="mmdet",
    optimizer=dict(type='AdamW', lr=lr, weight_decay=0.05),
    clip_grad=dict(max_norm=10, norm_type=2),
)

# learning rate: different from original paper where a warmup is used
param_scheduler = [
    dict(
        type='LinearLR',
        start_factor=1e-03,
        by_epoch=True,
        begin=0,
        end=5), # warmup
    dict(
        type='CosineRestartParamScheduler',
        param_name='lr',
        periods=[1],
        eta_min=1e-5,
        begin = 5,
        end=25,
        last_step=-1,
        by_epoch=True
    ),
]

randomness = dict(seed=2024)
visualizer=dict(type='Visualizer', vis_backends=[dict(type='TensorboardVisBackend')])

# update visualization hook
default_hooks = dict(
    visualization=dict(
        type='PlanningVisualizationHook',
        draw=True,
        interval=1,
        score_thr=0.3,
        show=True,
        vis_task='multi-modality_planning',
        wait_time=0,
        test_out_dir='results/InterFuser/',
        draw_gt=True,
        draw_pred=True,
        show_pcd_rgb=False,
        view_first_only=True,
        index_front_camera=0,
    )
)