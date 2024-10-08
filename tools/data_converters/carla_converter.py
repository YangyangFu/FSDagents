import os
from os.path import join
import gzip, json, pickle
import numpy as np
from pyquaternion import Quaternion
from tqdm import tqdm
from carla_converter_utils import calculate_cube_vertices,calculate_occlusion_stats,edges,DIS_CAR_SAVE
import cv2
import multiprocessing
import argparse
# All data in the Bench2Drive dataset are in the left-handed coordinate system.
# This code converts all coordinate systems (world coordinate system, vehicle coordinate system,
# camera coordinate system, and lidar coordinate system) to the right-handed coordinate system
# consistent with the nuscenes dataset.
# Nuscene coord: https://www.nuscenes.org/nuscenes#data-collection

DATAROOT = 'data-mini/carla/'
MAP_ROOT = 'data-mini/carla/maps'
OUT_DIR = 'data-mini/carla/infos'

MAX_DISTANCE = 75              # Filter bounding boxes that are too far from the vehicle
FILTER_Z_SHRESHOLD = 10        # Filter bounding boxes that are too high/low from the vehicle
FILTER_INVISINLE = True        # Filter bounding boxes based on visibility
NUM_VISIBLE_SHRESHOLD = 1      # Filter bounding boxes with fewer visible vertices than this value
NUM_OUTPOINT_SHRESHOLD = 7     # Filter bounding boxes where the number of vertices outside the frame is greater than this value in all cameras
CAMERAS = ['CAM_FRONT', 'CAM_FRONT_LEFT', 'CAM_FRONT_RIGHT', 'CAM_BACK', 'CAM_BACK_LEFT', 'CAM_BACK_RIGHT']
CAMERA_TO_FOLDER_MAP = {'CAM_FRONT':'rgb_front', 'CAM_FRONT_LEFT':'rgb_front_left', 'CAM_FRONT_RIGHT':'rgb_front_right', 'CAM_BACK':'rgb_back', 'CAM_BACK_LEFT':'rgb_back_left', 'CAM_BACK_RIGHT':'rgb_back_right'}

# stand: right-hand with x right, y down, z forward - Nuscenes front camera coord
# ue4: left-hand with x forward, y right, z up, same as lefthand ego, lefthand world, lefthand camera, lefthand lidar
stand_to_ue4_rotate = np.array([[ 0, 0, 1, 0],
                                [ 1, 0, 0, 0],
                                [ 0,-1, 0, 0],
                                [ 0, 0, 0, 1]])
# lidar coord: right-hand system with x right, y forward, z up - Nusecenes lidar coord
# righthand_ego: right-hand system with x forward, y left, z up - Nuscenes ego coord??? imu coord
lidar_to_righthand_ego = np.array([[  0, 1, 0, 0],
                                   [ -1, 0, 0, 0],
                                   [  0, 0, 1, 0],
                                   [  0, 0, 0, 1]])
# lefthand ego: left-hand with x forward, y right, z up: Carla ego coord
# lidar: right-hand with x right, y forward, z up: Nuscenes lidar coord
lefthand_ego_to_lidar = np.array([[ 0, 1, 0, 0],
                                  [ 1, 0, 0, 0],
                                  [ 0, 0, 1, 0],
                                  [ 0, 0, 0, 1]])
# left to right: this transformation could be used for any left-hand system to right-hand system
left2right = np.eye(4)
left2right[1,1] = -1

def apply_trans(vec,world2ego):
    vec = np.concatenate((vec,np.array([1])))
    t = world2ego @ vec
    return t[0:3]

def get_pose_matrix(dic):
    new_matrix = np.zeros((4,4))
    new_matrix[0:3,0:3] = Quaternion(axis=[0, 0, 1], radians=dic['theta']-np.pi/2).rotation_matrix
    new_matrix[0,3] = dic['x']
    new_matrix[1,3] = dic['y']
    new_matrix[3,3] = 1
    return new_matrix

def get_npc2world(npc):
    for key in ['world2vehicle','world2ego','world2sign','world2ped']:
        if key in npc.keys():
            npc2world = np.linalg.inv(np.array(npc[key]))
            yaw_from_matrix = np.arctan2(npc2world[1,0], npc2world[0,0])
            yaw = npc['rotation'][-1] / 180 * np.pi
            if abs(yaw-yaw_from_matrix)> 0.01:
                npc2world[0:3,0:3] = Quaternion(axis=[0, 0, 1], radians=yaw).rotation_matrix
            npc2world = left2right @ npc2world @ left2right
            return npc2world
    npc2world = np.eye(4)
    npc2world[0:3,0:3] = Quaternion(axis=[0, 0, 1], radians=npc['rotation'][-1]/180*np.pi).rotation_matrix
    npc2world[0:3,3] = np.array(npc['location'])
    return left2right @ npc2world @ left2right


def get_global_trigger_vertex(center,extent,yaw_in_degree):
    x,y = center[0],-center[1]
    dx,dy = extent[0],extent[1]
    yaw_in_radians = -yaw_in_degree/180*np.pi
    vertex_in_self = np.array([[ dx, dy],
                               [-dx, dy],
                               [-dx,-dy],
                               [ dx,-dy]])
    rotate_matrix = np.array([[np.cos(yaw_in_radians),-np.sin(yaw_in_radians)],
                              [np.sin(yaw_in_radians), np.cos(yaw_in_radians)]])
    rotated_vertex = (rotate_matrix @ vertex_in_self.T).T
    vertex_in_global = np.array([[x,y]]).repeat(4,axis=0) + rotated_vertex
    return vertex_in_global



def get_image_point(loc, K, w2c):
    point = np.array([loc[0], loc[1], loc[2], 1])
    point_camera = np.dot(w2c, point)
    point_camera = point_camera[0:3]
    depth = point_camera[2]
    point_img = np.dot(K, point_camera)
    point_img[0] /= point_img[2]
    point_img[1] /= point_img[2]
    return point_img[0:2], depth

def get_action(index):
	Discrete_Actions_DICT = {
		0:  (0, 0, 1, False),
		1:  (0.7, -0.5, 0, False),
		2:  (0.7, -0.3, 0, False),
		3:  (0.7, -0.2, 0, False),
		4:  (0.7, -0.1, 0, False),
		5:  (0.7, 0, 0, False),
		6:  (0.7, 0.1, 0, False),
		7:  (0.7, 0.2, 0, False),
		8:  (0.7, 0.3, 0, False),
		9:  (0.7, 0.5, 0, False),
		10: (0.3, -0.7, 0, False),
		11: (0.3, -0.5, 0, False),
		12: (0.3, -0.3, 0, False),
		13: (0.3, -0.2, 0, False),
		14: (0.3, -0.1, 0, False),
		15: (0.3, 0, 0, False),
		16: (0.3, 0.1, 0, False),
		17: (0.3, 0.2, 0, False),
		18: (0.3, 0.3, 0, False),
		19: (0.3, 0.5, 0, False),
		20: (0.3, 0.7, 0, False),
		21: (0, -1, 0, False),
		22: (0, -0.6, 0, False),
		23: (0, -0.3, 0, False),
		24: (0, -0.1, 0, False),
		25: (1, 0, 0, False),
		26: (0, 0.1, 0, False),
		27: (0, 0.3, 0, False),
		28: (0, 0.6, 0, False),
		29: (0, 1.0, 0, False),
		30: (0.5, -0.5, 0, True),
		31: (0.5, -0.3, 0, True),
		32: (0.5, -0.2, 0, True),
		33: (0.5, -0.1, 0, True),
		34: (0.5, 0, 0, True),
		35: (0.5, 0.1, 0, True),
		36: (0.5, 0.2, 0, True),
		37: (0.5, 0.3, 0, True),
		38: (0.5, 0.5, 0, True),
		}
	throttle, steer, brake, reverse = Discrete_Actions_DICT[index]
	return throttle, steer, brake


def gengrate_map(map_root):
    map_infos = {}
    for file_name in os.listdir(map_root):
        if '.npz' in file_name:
            map_info = dict(np.load(join(map_root,file_name), allow_pickle=True)['arr'])
            town_name = file_name.split('_')[0]
            map_infos[town_name] = {} 
            lane_points = []
            lane_types = []
            lane_sample_points = []
            trigger_volumes_points = []
            trigger_volumes_types = []
            trigger_volumes_sample_points = []
            for road_id, road in map_info.items():
                for lane_id, lane in road.items():
                    if lane_id == 'Trigger_Volumes':
                        for single_trigger_volume in lane:
                            points = np.array(single_trigger_volume['Points'])
                            points[:,1] *= -1 #left2right
                            trigger_volumes_points.append(points)
                            trigger_volumes_sample_points.append(points.mean(axis=0))
                            trigger_volumes_types.append(single_trigger_volume['Type'])
                    else:
                        for single_lane in lane:
                            points = np.array([raw_point[0] for raw_point in single_lane['Points']])
                            points[:,1] *= -1
                            lane_points.append(points)
                            lane_types.append(single_lane['Type'])
                            lane_lenth = points.shape[0]
                            if lane_lenth % 50 != 0:
                                devide_points = [50*i for i in range(lane_lenth//50+1)]
                            else:
                                devide_points = [50*i for i in range(lane_lenth//50)]
                            devide_points.append(lane_lenth-1)
                            lane_sample_points_tmp = points[devide_points]
                            lane_sample_points.append(lane_sample_points_tmp)
            map_infos[town_name]['lane_points'] = lane_points
            map_infos[town_name]['lane_sample_points'] = lane_sample_points
            map_infos[town_name]['lane_types'] = lane_types
            map_infos[town_name]['trigger_volumes_points'] = trigger_volumes_points
            map_infos[town_name]['trigger_volumes_sample_points'] = trigger_volumes_sample_points
            map_infos[town_name]['trigger_volumes_types'] = trigger_volumes_types
    with open(join(OUT_DIR,'b2d_map_infos_11.pkl'),'wb') as f:
        pickle.dump(map_infos,f)


# The map is too big for my computer. need save it into different chunks
def gengrate_map_chunk(map_root):
    map_infos = {}
    for file_name in os.listdir(map_root):
        if '.npz' in file_name:
            map_info = dict(np.load(join(map_root,file_name), allow_pickle=True)['arr'])
            town_name = file_name.split('_')[0]
            map_infos[town_name] = {} 
            lane_points = []
            lane_types = []
            lane_sample_points = []
            trigger_volumes_points = []
            trigger_volumes_types = []
            trigger_volumes_sample_points = []
            for road_id, road in map_info.items():
                for lane_id, lane in road.items():
                    if lane_id == 'Trigger_Volumes':
                        for single_trigger_volume in lane:
                            points = np.array(single_trigger_volume['Points']).astype(np.float32)
                            points[:,1] *= -1 #left2right
                            trigger_volumes_points.append(points)
                            trigger_volumes_sample_points.append(points.mean(axis=0))
                            trigger_volumes_types.append(single_trigger_volume['Type'])
                    else:
                        for single_lane in lane:
                            points = np.array([raw_point[0] for raw_point in single_lane['Points']]).astype(np.float32)
                            points[:,1] *= -1
                            lane_points.append(points)
                            lane_types.append(single_lane['Type'])
                            lane_lenth = points.shape[0]
                            if lane_lenth % 50 != 0:
                                devide_points = [50*i for i in range(lane_lenth//50+1)]
                            else:
                                devide_points = [50*i for i in range(lane_lenth//50)]
                            devide_points.append(lane_lenth-1)
                            lane_sample_points_tmp = points[devide_points]
                            lane_sample_points.append(lane_sample_points_tmp)
            map_infos[town_name]['lane_points'] = lane_points
            #map_infos[town_name]['lane_sample_points'] = lane_sample_points
            #map_infos[town_name]['lane_types'] = lane_types
            #map_infos[town_name]['trigger_volumes_points'] = trigger_volumes_points
            #map_infos[town_name]['trigger_volumes_sample_points'] = trigger_volumes_sample_points
            #map_infos[town_name]['trigger_volumes_types'] = trigger_volumes_types
    with open(join(OUT_DIR,'b2d_map_infos_11.pkl'),'wb') as f:
        pickle.dump(map_infos,f)

#TODO: map of 1.5G is too big to be loadded in a 32GB ram computer.
def generate_map_chunk_lane_points(map_root):
    map_infos = {}
    for file_name in os.listdir(map_root):
        if '.npy' in file_name:
            map_info = dict(np.load(join(map_root,file_name), allow_pickle=True)['arr'])
            town_name = file_name.split('_')[0]
            map_infos[town_name] = {} 
            lane_points = []
            lane_types = []
            lane_sample_points = []
            trigger_volumes_points = []
            trigger_volumes_types = []
            trigger_volumes_sample_points = []
            print(len(map_info))
            print(sssss)
            for road_id, road in map_info.items():
                for lane_id, lane in road.items():
                    if lane_id == 'Trigger_Volumes':
                        pass
                    else:
                        for single_lane in lane:
                            points = np.array([raw_point[0] for raw_point in single_lane['Points']]).astype(np.float32)
                            points[:,1] *= -1
                            lane_points.append(points)
                            lane_types.append(single_lane['Type'])
                            #lane_lenth = points.shape[0]
                            #if lane_lenth % 50 != 0:
                            #    devide_points = [50*i for i in range(lane_lenth//50+1)]
                            #else:
                            #    devide_points = [50*i for i in range(lane_lenth//50)]
                            #devide_points.append(lane_lenth-1)
                            #lane_sample_points_tmp = points[devide_points]
                            #lane_sample_points.append(lane_sample_points_tmp)
            map_infos[town_name]['lane_points'] = lane_points
            #map_infos[town_name]['lane_sample_points'] = lane_sample_points
            map_infos[town_name]['lane_types'] = lane_types
            #map_infos[town_name]['trigger_volumes_points'] = trigger_volumes_points
            #map_infos[town_name]['trigger_volumes_sample_points'] = trigger_volumes_sample_points
            #map_infos[town_name]['trigger_volumes_types'] = trigger_volumes_types
    with open(join(OUT_DIR,'b2d_map_infos_11.pkl'),'wb') as f:
        pickle.dump(map_infos,f)

def preprocess(folder_list,idx,tmp_dir,train_or_val):

    data_root = DATAROOT
    cameras = CAMERAS
    final_data = []
    if idx == 0:
        folders = tqdm(folder_list)
    else:
        folders = folder_list

    for folder_name in folders:
        folder_path = join(data_root, folder_name)
        last_position_dict = {}
        for ann_name in sorted(os.listdir(join(folder_path,'anno')),key= lambda x: int(x.split('.')[0])):
            position_dict = {}
            frame_data = {}
            cam_gray_depth = {}
            with gzip.open(join(folder_path,'anno',ann_name), 'rt', encoding='utf-8') as gz_file:
                anno = json.load(gz_file) 
            frame_data['folder'] = folder_name
            frame_data['town_name'] =  folder_name.split('/')[1].split('_')[1]
            frame_data['command_far_xy'] = np.array([anno['x_command_far'],-anno['y_command_far']])
            frame_data['command_far'] = anno['command_far']
            frame_data['command_near_xy'] = np.array([anno['x_command_near'],-anno['y_command_near']])
            frame_data['command_near'] = anno['command_near']
            frame_data['frame_idx'] = int(ann_name.split('.')[0])
            frame_data['ego_yaw'] = -np.nan_to_num(anno['theta'],nan=np.pi)+np.pi/2  
            frame_data['ego_translation'] = np.array([anno['x'],-anno['y'],0])
            frame_data['ego_vel'] = np.array([anno['speed'],0,0]) # ego speed in ego coord
            frame_data['ego_accel'] = np.array([anno['acceleration'][0],-anno['acceleration'][1],anno['acceleration'][2]])
            frame_data['ego_rotation_rate'] = -np.array(anno['angular_velocity'])
            frame_data['ego_size'] = np.array([anno['bounding_boxes'][0]['extent'][1],anno['bounding_boxes'][0]['extent'][0],anno['bounding_boxes'][0]['extent'][2]])*2
            
            # NOTE: left2right is not only orthogonal, but also self-inverse, that is right2left = left2right
            # right-hand world to right-hand ego = left2right @ leftworld 2 left ego @ right2left
            world2ego = left2right @ anno['bounding_boxes'][0]['world2ego'] @ left2right
            frame_data['world2ego'] = world2ego
            if frame_data['frame_idx'] == 0:
                expert_file_path = join(folder_path,'expert_assessment','-0001.npz')
            else:
                expert_file_path = join(folder_path,'expert_assessment',str(frame_data['frame_idx']-1).zfill(5)+'.npz')
            expert_data = np.load(expert_file_path,allow_pickle=True)['arr_0']
            action_id = expert_data[-1]
            # value = expert_data[-2]
            # expert_feature = expert_data[:-2]
            throttle, steer, brake = get_action(action_id)
            frame_data['brake'] = brake
            frame_data['throttle'] = throttle
            frame_data['steer'] = steer
            #frame_data['action_id'] = action_id
            #frame_data['value'] = value
            #frame_data['expert_feature'] = expert_feature
            ###get sensor infos###
            sensor_infos = {}
            for cam in CAMERAS:
                sensor_infos[cam] = {}
                # right camera 2 right ego = left ego 2 right ego @ left camera 2 left ego @ right camera 2 left camera
                sensor_infos[cam]['cam2ego'] = left2right @ np.array(anno['sensors'][cam]['cam2ego']) @ stand_to_ue4_rotate 
                sensor_infos[cam]['intrinsic'] = np.array(anno['sensors'][cam]['intrinsic'])
                # nuscene world 2 nuscene camera = left camera 2 right camera @ left world 2 left camera @ right world 2 left world
                sensor_infos[cam]['world2cam'] = np.linalg.inv(stand_to_ue4_rotate) @ np.array(anno['sensors'][cam]['world2cam']) @left2right
                sensor_infos[cam]['data_path'] = join(folder_name,'camera',CAMERA_TO_FOLDER_MAP[cam],ann_name.split('.')[0]+'.jpg')
                cam_gray_depth[cam] = cv2.imread(join(data_root,sensor_infos[cam]['data_path']).replace('rgb_','depth_').replace('.jpg','.png'))[:,:,0]
            sensor_infos['LIDAR_TOP'] = {}
            # right-hand lidar 2 right-hand ego = left2right @ left lidar 2 left ego @ right lidar 2 left lidar
            # right lidar 2 left lidar = right ego 2 left lidar @ right lidar 2 right ego = right2left @ right lidar 2 right ego
            sensor_infos['LIDAR_TOP']['lidar2ego'] = left2right @ np.array(anno['sensors']['LIDAR_TOP']['lidar2ego']) @ left2right @ lidar_to_righthand_ego
            # righthand world 2 righthand lidar = lefthand lidar 2 righthand lidar @ lefthand world 2 lefthand lidar @ righthand world 2 lefthand world
            world2lidar = lefthand_ego_to_lidar @ np.array(anno['sensors']['LIDAR_TOP']['world2lidar']) @ left2right
            sensor_infos['LIDAR_TOP']['world2lidar'] = world2lidar
            frame_data['sensors'] = sensor_infos
            ###get bounding_boxes infos###
            gt_boxes = []
            gt_names = []
            gt_ids = []
            num_points_list = []
            npc2world_list = []
            affected_by_lights = []
            affected_by_signs = []
            
            for npc in anno['bounding_boxes']:
                if npc['class'] == 'ego_vehicle': 
                    # get road and lane id
                    ego_road_id = npc['road_id']
                    ego_lane_id = npc['lane_id']
                    ego_section_id = npc['section_id']
                    continue
                if npc['distance'] > MAX_DISTANCE: continue
                if abs(npc['location'][2] - anno['bounding_boxes'][0]['location'][2]) > FILTER_Z_SHRESHOLD: continue
                center = np.array([npc['center'][0],-npc['center'][1],npc['center'][2]]) # left hand -> right hand
                extent = np.array([npc['extent'][1],npc['extent'][0],npc['extent'][2]])  # lwh -> wlh
                position_dict[npc['id']] = center
                local_center = apply_trans(center, world2lidar)
                size = extent * 2 
                if 'world2vehicle' in npc.keys():
                    world2vehicle = left2right @ np.array(npc['world2vehicle'])@left2right
                    vehicle2lidar = world2lidar @ np.linalg.inv(world2vehicle) 
                    yaw_local = np.arctan2(vehicle2lidar[1,0], vehicle2lidar[0,0])

                else:
                    yaw_local = -npc['rotation'][-1]/180*np.pi - frame_data['ego_yaw'] +np.pi / 2  
                yaw_local_in_lidar_box = -yaw_local - np.pi / 2  
                while yaw_local < -np.pi:
                    yaw_local += 2*np.pi
                while yaw_local > np.pi:
                    yaw_local -= 2*np.pi  
                if 'speed' in npc.keys():
                    if 'vehicle' in npc['class']:  # only vehicles have correct speed
                        speed = npc['speed']
                    else:
                        if npc['id'] in last_position_dict.keys():  #calculate speed for other object
                            speed = np.linalg.norm((center-last_position_dict[npc['id']])[0:2]) * 10
                        else:
                            speed = 0
                else:
                    speed = 0
                if 'num_points' in npc.keys():
                    num_points = npc['num_points']
                else:
                    num_points = -1
                npc2world = get_npc2world(npc)
                speed_x = speed * np.cos(yaw_local)
                speed_y = speed * np.sin(yaw_local)

                ###fliter_bounding_boxes###
                if FILTER_INVISINLE:
                    valid = False
                    box2lidar = np.eye(4)
                    box2lidar[0:3,0:3] = Quaternion(axis=[0, 0, 1], radians=yaw_local).rotation_matrix
                    box2lidar[0:3,3] = local_center
                    lidar2box = np.linalg.inv(box2lidar)
                    raw_verts = calculate_cube_vertices(local_center,extent)
                    verts = []
                    for raw_vert in raw_verts:
                        tmp = np.dot(lidar2box, [raw_vert[0], raw_vert[1], raw_vert[2],1])
                        tmp[0:3] += local_center
                        verts.append(tmp.tolist()[:-1])
                    for cam in cameras:
                        lidar2cam = np.linalg.inv(frame_data['sensors'][cam]['cam2ego']) @ sensor_infos['LIDAR_TOP']['lidar2ego']
                        test_points = [] 
                        test_depth = []
                        for vert in verts:
                            point, depth = get_image_point(vert, frame_data['sensors'][cam]['intrinsic'], lidar2cam)
                            if depth > 0:
                                test_points.append(point)
                                test_depth.append(depth)

                        num_visible_vertices, num_invisible_vertices, num_vertices_outside_camera, colored_points = calculate_occlusion_stats(np.array(test_points), np.array(test_depth),  cam_gray_depth[cam], max_render_depth=MAX_DISTANCE)
                        if num_visible_vertices>NUM_VISIBLE_SHRESHOLD and num_vertices_outside_camera<NUM_OUTPOINT_SHRESHOLD:
                            valid = True
                            break
                else:
                    valid = True
                if valid:
                    npc2world_list.append(npc2world)
                    num_points_list.append(num_points)            
                    gt_boxes.append(np.concatenate([local_center,size,np.array([yaw_local_in_lidar_box,speed_x,speed_y])]))
                    gt_names.append(npc['type_id'])
                    gt_ids.append(int(npc['id']))
                
                # check if npc is traffic lights, signs, and affects ego
                if npc['class'] == 'traffic_light' and npc['affects_ego']:
                    affected_by_lights.append(npc['id'])
                elif npc['class'] == 'traffic_sign' and npc['affects_ego']:
                    affected_by_signs.append(npc['id'])
            
            """    
            # check if ego is affected by junction
            affected_by_junction = 0
            map_dir = join(MAP_ROOT, frame_data['town_name'] + '_HD_map.npz')
            map_info = dict(np.load(map_dir, allow_pickle=True)['arr'])
            print('ego location: ', frame_data['ego_translation'], ego_section_id)
            for seg in map_info[ego_road_id][ego_lane_id]:
                if seg['Type'] == 'Center':
                    key = 'Points'
                    # find waypoints
                    min_distance = 5
                    min_idx = -1
                    for idx, point in enumerate(seg[key]):
                        point_xyz = [point[0][0], -point[0][1], point[0][2]] # to right hand
                        dist = np.linalg.norm(np.array(point_xyz) - frame_data['ego_translation'])
                        if dist < min_distance:
                            min_distance = dist
                            min_idx= idx
      
                    print("min distance found: ", min_distance) 
                    # check if the waypoint is a junction
                    if min_idx == -1: continue
                    point = seg[key][min_idx]
                    if len(point) == 3 and point[2]:
                        affected_by_junction = 1
                        break
            """         
            if len(gt_boxes) == 0:
                continue

            last_position_dict = position_dict.copy()    
            gt_ids = np.array(gt_ids)
            gt_names = np.array(gt_names)
            num_points_list = np.array(num_points_list)
            gt_boxes = np.stack(gt_boxes)
            npc2world = np.stack(npc2world_list)
            frame_data['gt_ids'] = gt_ids
            frame_data['gt_boxes'] = gt_boxes
            frame_data['gt_names'] = gt_names
            frame_data['num_points'] = num_points_list
            frame_data['npc2world'] = npc2world
            # if ego is affected by traffic lights or signs
            frame_data['affected_by_lights'] = np.array(affected_by_lights)
            frame_data['affected_by_signs'] = np.array(affected_by_signs)
            #frame_data['affected_by_junction'] = affected_by_junction
            final_data.append(frame_data)
    
    os.makedirs(join(OUT_DIR,tmp_dir),exist_ok=True)
    with open(join(OUT_DIR,tmp_dir,'b2d_infos_'+train_or_val+'_'+str(idx)+'.pkl'),'wb') as f:
        pickle.dump(final_data,f)


def generate_infos(folder_list,workers,train_or_val,tmp_dir):

    folder_num = len(folder_list)
    devide_list = [(folder_num//workers)*i for i in range(workers)]
    devide_list.append(folder_num)
    for i in range(workers):
        sub_folder_list = folder_list[devide_list[i]:devide_list[i+1]]
        process = multiprocessing.Process(target=preprocess, args=(sub_folder_list,i,tmp_dir,train_or_val))
        process.start()
        process_list.append(process)
    for i in range(workers):
        process_list[i].join()
    union_data = []
    for i in range(workers):
        with open(join(OUT_DIR,tmp_dir,'b2d_infos_'+train_or_val+'_'+str(i)+'.pkl'),'rb') as f:
            data = pickle.load(f)
        union_data.extend(data)
    with open(join(OUT_DIR,'b2d_infos_'+train_or_val+'.pkl'),'wb') as f:
        pickle.dump(union_data,f)

if __name__ == "__main__":

    
    os.makedirs(OUT_DIR,exist_ok=True)
    argparser = argparse.ArgumentParser(description=__doc__)
    argparser.add_argument('--workers',type=int, default= 16, help='num of workers to prepare dataset')
    argparser.add_argument('--tmp_dir', default="tmp_data", )
    args = argparser.parse_args()    
    workers = args.workers
    process_list = []
    with open('data-mini/carla/splits/bench2drive_base_train_val_split.json','r') as f:
        train_val_split = json.load(f)
        
    all_folder = os.listdir(join(DATAROOT,'v1'))
    train_list = []
    for foldername in all_folder:
        if 'Town' in foldername and 'Route' in foldername and 'Weather' in foldername and not join('v1',foldername) in train_val_split['val']:
            train_list.append(join('v1',foldername))   
    print('processing train data...')
    #generate_infos(train_list,workers,'train',args.tmp_dir)
    process_list = []
    print('processing val data...')
    #generate_infos(train_val_split['val'],workers,'val',args.tmp_dir)
    
    print('processing map data...')
    generate_map_chunk_lane_points(MAP_ROOT)
    print('finish!')