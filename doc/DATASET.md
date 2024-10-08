# Dataset
Agent's pose in world is the transformation from agent to world.

## Coordinate Systems 
The following figure summarizes different coordinates used in different dataset.

![coordinate](./assets/coordinates.png)

## CARLA Dataset

### Raw Data in Hugging Face
The original data in hugging face are recorded in CARLA coordinates, which is a left-hand system.
The data are stored in different frames during collection. 

```
- point cloud
  - lidar points from the simulator are originally in CARLA lidar frame, and saved in CARLA ego frame using transformations between ego and lidar.

- annotations:
    - bounding_bboxes
        - agent xx
            - class/type/id, ...
            - location: x,y,z in Carla/UE4 world coordinate
            - rotation: in Carla/UE4 world
            - bbox_loc: x, y, z in ego coordinate
            - center: center point in Carla world coordinate
            - extent: extension length (half of size) in Carla world coordinate
            - world2ego: Carla world to ego transformation
            - ...
```

### Convert to Nuscene Coordinate
The second round of processing the data is performed using `prepare_B2D.py`, which annotate the above data into `right hand Nuscene coordinates`


The following keys are stored in the annotation file as `*.pkl`
```
    - frame_idx -> current frame idx
    - folder -> data folder for current sample, e.g., `v1/DynamicObjectCrossing_TownXX_RouteXX_WeatherXX`
    - town_name -> town name, e.g., TownXX
    - command_far_xy -> farther waypoint in world coordinates
    - command_far -> command to farther waypoint
    - command_near_xy -> nearby waypoint in world coordinates
    - command_near -> command to nearby command
    - ego_yaw -> in radians. 
    - ego_translation -> 3D
    - ego_vel -> 3D
    - ego_accel -> 3D
    - ego_rotation_rate ->3D
    - ego_size -> 3D
    - ego_affected_by_lights: 
    - ego_affected_by_signs:
    - ego_affected_by_junction:
    - world2ego -> (4, 4)
    - brake -> [0, 1]
    - throttle -> [0, 1]
    - steer -> [0, 1]
    - gt_ids -> id of instances in the scence (multi view camera, or lidar or combined?) (N,)
    - gt_boxes -> boxes in lidar coordinates for each npc instance including traffic sign, traffic light, vehicle, etc, (N, 9) with (3d center in lidar coord, 3d size (extent x 2), yaw in lidar coord, speed x, speed y)
    - gt_names -> class name in Carla for each instance, (N, )
    - num_points -> number of lidar points hitting on the bounding box. used to filter invisible instance.
    - npc2world -> transformation matrix for npc (N, 4, 4)
    - sensors
        - CAM_XXX
            - cam2ego
            - instrinsic
            - world2cam
            - data_path

        - LIDAR_TOP
            - lidar2ego
            - world2lidar
```


### Convert to Planning Coordinate
When constructing the dataset/dataloader, before entering the data pipeline, the data are processed into Planning/MMDET3D coordinates to keep consisent during the whole training and testing process.


## Nuscenes Dataset

### Raw Nuscences Dataset

### Convert to Planning Coordinate

## Waymo Dataset

### Raw Nuscences Dataset

### Convert to Planning Coordinate

## QUESTIONS

- Q1: For nuscene dataset in MMDET3D, the following data processing procedures are performed when formating a MMDET3D dataset:
    1. downlown original nuscene dataset
    2. use `create_data.py` provided by mmdet3d to process the annotation file and raw data to mmdet3d format, which generates a a few *.pkl files
        - the ground truth bboxes are in global frame as descrubed [here](https://github.com/nutonomy/nuscenes-devkit/tree/master/python-sdk/nuscenes/eval/detection), are they processed into lidara frame at this step?
    
            - **YES**. The ground truth bboxes in global frame are processed into lidar coordinate as shown [here](https://github.com/open-mmlab/mmdetection3d/blob/fe25f7a51d36e3702f961e198894580d83c4387b/tools/dataset_converters/nuscenes_converter.py#L174) 

    3. the mmdet3d dataset then is built on these *.pkl files and raw data


- Q2: How is BEVFormer deal with BEV targets/labels? The original 3d bboxes annotation if for the whole view. If some object is outside of BEV grid as defined by the `bev_size`, does BEVformer filter out these targets?
    - I posted a question [here](https://github.com/fundamentalvision/BEVFormer/issues/275), and I think they just use all the ground truth labels as their BEV size is similar to the lidar range.