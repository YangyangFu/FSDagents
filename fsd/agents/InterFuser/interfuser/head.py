"""GRU head for predicting waypoints
"""
from typing import List, Optional
import torch
import torch.nn as nn

from mmengine.model import BaseModule
from fsd.registry import TASK_UTILS, MODELS
from fsd.utils import ConfigType, OptConfigType, DataSampleType

@TASK_UTILS.register_module('interfuser_gru_waypoint')
class GRUWaypointHead(BaseModule):
    """GRU head for predicting waypoints torwards a goal point.
    The 2D goal point from global planner is first projected to a high-dimension (e.g, 64), which is then used as initial hidden state of GRU.
    The GRU input is the queried feature from transformers.
    The GRU output is the latent representation of the differential displacement between waypoints, which is then projected to 2D displacement, 
    and accumulated to get the waypoint.  
    
    Implementation from:
        `Safety-Enhanced Autonomous Driving using Interpretable Sensor Fusion Transformer`
        
    """
    def __init__(self,
                 num_waypoints: int, 
                 input_size: int, 
                 hidden_size: int=64, 
                 num_layers: int = 1, 
                 dropout: float = 0., 
                 batch_first: bool = False,
                 loss_cfg: ConfigType = dict(
                     type='MaskedSmoothL1Loss', 
                     beta=0.5, 
                     reduction='mean', 
                     loss_weight=1.0),
                 waypoints_weights: Optional[List[float]] = None,
                 init_cfg: OptConfigType = None):
        super(GRUWaypointHead, self).__init__(init_cfg=init_cfg)
        self.linear1 = nn.Linear(2, hidden_size)
        self.gru = nn.GRU(input_size, hidden_size, num_layers, dropout=dropout, batch_first=batch_first)
        self.linear2 = nn.Linear(hidden_size, 2)
        self.batch_first = batch_first
        self.num_layers = num_layers
        
        # loss fcn
        self.loss_fcn = MODELS.build(loss_cfg)
        # weights for each waypoint
        self.num_waypoints = num_waypoints
        self.waypoints_weights = waypoints_weights
        if self.waypoints_weights is not None:
            assert self.num_waypoints == len(self.waypoints_weights)
            # (L, ) -> (1, L, 1)
            self.waypoints_weights = torch.Tensor(self.waypoints_weights).unsqueeze(0).unsqueeze(-1)

    def forward(self, 
                hidden_states: torch.Tensor, 
                goal_points: torch.Tensor) -> torch.Tensor:
        """
        
        Args:
            hidden_states (torch.Tensor): Features from transformer decoder with
                shape (B, L, input_size) 
            goal_point (torch.Tensor): with shape (B, 2)

        Returns:
            torch.Tensor: with shape (B, L, 2) 
        """
        assert hidden_states.dim() == 3, f"hidden_states must have 3 dimensions, got {hidden_states.dim()}"
        assert goal_points.dim() == 2, f"goal_points must have 2 dimensions, got {goal_points.dim()}"
        
        L = hidden_states.size(1) 
        assert L == self.num_waypoints, f"Number of waypoints {L} must be equal to the number of waypoints {self.num_waypoints}"
        
        # (B, 2) -> (B, hidden_size) -> (1, B, hidden_size)
        z = self.linear1(goal_points).unsqueeze(0).repeat(self.num_layers, 1, 1)
        # (B, L, hidden_size) or (L, B, hidden_size)
        if not self.batch_first:
            hidden_states = hidden_states.permute(1, 0, 2)    
        output, _ = self.gru(hidden_states, z)
    
        # (B, L, 2) or (L, B, 2)
        output = self.linear2(output)
        
        if not self.batch_first:
            output = output.permute(1, 0, 2)
            
        # accumulate the displacement
        output = torch.cumsum(output, dim=1)

        # (B, L, 2) 
        return output


    def loss(self, hidden_states: torch.Tensor, 
             goal_points: torch.Tensor, 
             target_waypoints: torch.Tensor,
             target_waypoints_masks: Optional[torch.Tensor]=None) -> torch.Tensor:
        """_summary_

        Args:
            hidden_states (torch.Tensor): (B, L, input_size)
            goal_points (torch.Tensor): (B, 2) 
            target_waypoints (torch.Tensor): (B, L, 2)
            target_waypoints_masks (Optional[torch.Tensor], optional): (B, L) or (B, L ,2).
                Defaults to None.

        Returns:
            torch.Tensor: _description_
        """
        # forward
        pred_waypoints = self(hidden_states, goal_points)
        
        # resize
        if target_waypoints_masks is not None \
            and target_waypoints_masks.dim() == 2:
            target_waypoints_masks = target_waypoints_masks.unsqueeze(-1).repeat(1, 1, 2)
        if target_waypoints_masks is not None \
            and target_waypoints_masks.dim() == 3:
                assert target_waypoints_masks.size(2) == 2, f"target_waypoints_masks must have 2 channels, got {target_waypoints_masks.size(2)}"
        
        B, L, _ = pred_waypoints.size()
        weight = self.waypoints_weights.repeat(B, 1, 2)
    
        weight = weight.to(pred_waypoints.device)
        
        return self.loss_fcn(pred_waypoints, 
                             target_waypoints, 
                             weight=weight, 
                             mask=target_waypoints_masks)
    
class ObjectDensityLoss(BaseModule):
    """Loss for object density map prediction in InterFuser

        Density map has a shape of (R, R, 7). The 7 channels are:
            - 0: occupancy at the current grid
            - 1-2: 2-D offset to grid center
            - 3-4: 2-D bounding box
            - 5: heading angle
            - 6: velocity
    """
    def __init__(self, 
                 loss_cfg: ConfigType = dict(
                     type='mmdet.L1Loss', 
                     reduction='mean', 
                     loss_weight=1.0),
                 init_cfg: OptConfigType = None):
        super(ObjectDensityLoss, self).__init__(init_cfg=init_cfg)
        self.loss_fcn = MODELS.build(loss_cfg)
        
    def forward(self, pred: torch.Tensor, 
                target: torch.Tensor, 
                weights: torch.Tensor = torch.Tensor([0.25, 0.25, 0.02])) -> torch.Tensor:
        """_summary_

        Args:
            pred (torch.Tensor): (B, L, 7)
            target (torch.Tensor): (B, L, 7)
            weights (torch.Tensor, optional): (3, ). Defaults to torch.Tensor([0.25, 0.25, 0.02]).

        Returns:
            torch.Tensor: _description_
        """
        target_1_mask = target[:, :, 0].ge(0.01)
        target_0_mask = target[:, :, 0].le(0.01)
        target_prob_1 = torch.masked_select(target[:, :, 0], target_1_mask)
        output_prob_1 = torch.masked_select(pred[:, :, 0], target_1_mask)
        target_prob_0 = torch.masked_select(target[:, :, 0], target_0_mask)
        output_prob_0 = torch.masked_select(pred[:, :, 0], target_0_mask)
        if target_prob_1.numel() == 0:
            loss_prob_1 = 0
        else:
            loss_prob_1 = self.loss_fcn(output_prob_1, target_prob_1)
        if target_prob_0.numel() == 0:
            loss_prob_0 = 0
        else:
            loss_prob_0 = self.loss_fcn(output_prob_0, target_prob_0)
        loss_1 = 0.5 * loss_prob_0 + 0.5 * loss_prob_1

        output_1 = pred[target_1_mask][:][:, 1:6]
        target_1 = target[target_1_mask][:][:, 1:6]
        if target_1.numel() == 0:
            loss_2 = 0
        else:
            loss_2 = self.loss_fcn(target_1, output_1)

        # speed pred loss
        output_2 = pred[target_1_mask][:][:, 6]
        target_2 = target[target_1_mask][:][:, 6]
        if target_2.numel() == 0:
            loss_3 = 0
        else:
            loss_3 = self.loss_fcn(target_2, output_2)
        
        # (3, ) * (3, ) -> (3, ) -> ()
        return loss_1*weights[0] + loss_2*weights[1] + loss_3*weights[2]
        
@TASK_UTILS.register_module('interfuser_object_density')
class ObjectDensityHead(BaseModule):
    """Head to predict density map from the output of transformer.

        The paper simply uses a 3-layer MLP to predict the 7 outputs
    """
    # TODO: this seems strange, e.g., only two layers here
    def __init__(self, input_size: int, 
                 hidden_size: int = 64, 
                 output_size: int = 7, 
                 loss_cfg: OptConfigType = dict(
                     type='mmdet.L1Loss', 
                     reduction='mean', 
                     loss_weight=1.0
                 ),
                 init_cfg: OptConfigType = None):
        super(ObjectDensityHead, self).__init__(init_cfg=init_cfg)
        self.mlp = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, output_size),
            nn.Sigmoid(), 
        )

        self.loss_fcn = ObjectDensityLoss(loss_cfg)
        
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x (torch.Tensor): with shape (B, L, input_size)

        Returns:
            torch.Tensor: with shape (B, L, output_size)
        """
        return self.mlp(x)

    def loss(self, x: torch.Tensor, 
             target: torch.Tensor) -> torch.Tensor:
        preds = self(x)
        return self.loss_fcn(preds, target)
    
#TODO: No sigmoid in original paper ???
@TASK_UTILS.register_module('interfuser_traffic_rule')
class ClassificationHead(BaseModule):
    """Traffic rule head to predict traffic rule from the output of transformer.

        The paper simply uses a 1-layer linear layer to predict 2 outputs for each traffic rule (i.e., stop sign, traffic light, and is_junction)
    """

    def __init__(self, input_size: int, 
                 output_size: int = 2,
                 loss_cfg: ConfigType = dict(
                     type='mmdet.CrossEntropyLoss', 
                     use_sigmoid=True, 
                     reduction='mean',
                     loss_weight=1.0),
                 init_cfg: OptConfigType = None):
        super(ClassificationHead, self).__init__(init_cfg=init_cfg)
        self.linear = nn.Linear(input_size, output_size)
        
        # loss 
        self.loss_fcn = MODELS.build(loss_cfg)
        
    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """
        Args:
            hidden_states (torch.Tensor): with shape (B, input_size)

        Returns:
            torch.Tensor: with shape (B, output_size)
        """
        return self.linear(hidden_states)

    def loss(self, 
             hidden_states: torch.Tensor, 
             target: torch.Tensor) -> torch.Tensor:
        preds = self(hidden_states)
        return self.loss_fcn(preds, target)

@TASK_UTILS.register_module('interfuser_heads')     
class InterFuserHead(BaseModule):
    def __init__(self,
                 num_waypoints_queries: int, 
                 num_traffic_rule_queries: int,
                 num_object_density_queries: int,
                 waypoints_head: ConfigType,
                 object_density_head: ConfigType,
                 junction_head: ConfigType,
                 stop_sign_head: ConfigType,
                 traffic_light_head: ConfigType,
                 init_cfg: OptConfigType = None):
        super(InterFuserHead, self).__init__(init_cfg=init_cfg)

        # number of queries
        self.num_waypoints_queries = num_waypoints_queries
        self.num_traffic_rule_queries = num_traffic_rule_queries
        self.num_object_density_queries = num_object_density_queries
        self.num_queries = self.num_object_density_queries + self.num_traffic_rule_queries + self.num_waypoints_queries
        
        assert waypoints_head['num_waypoints']== self.num_waypoints_queries, \
            f"waypoints_head num_waypoints {waypoints_head['num_waypoints']} must \
                be equal to InterfuserHead num_waypoints_queries {self.num_waypoints_queries}"
        
        
        # heads
        self.waypoints_head = TASK_UTILS.build(waypoints_head)
        self.object_density_head = TASK_UTILS.build(object_density_head)
        self.junction_head = TASK_UTILS.build(junction_head)
        self.stop_sign_head = TASK_UTILS.build(stop_sign_head)
        self.traffic_light_head = TASK_UTILS.build(traffic_light_head)


    def forward(self, hidden_states: torch.Tensor,
                goal_point: torch.Tensor,
                ego_velocity: torch.Tensor) -> dict:
        """
        Args:
            hidden_states (torch.Tensor): with shape (B, L, input_size)
            goal_point (torch.Tensor): with shape (B, 2)
            ego_velocity (torch.Tensor): with shape (B, 1)

        Returns:
            dict: with keys:
                - object_density (torch.Tensor): with shape (B, L, 7)
                - junction (torch.Tensor): with shape (B, 2)
                - stop_sign (torch.Tensor): with shape (B, 2)
                - traffic_light (torch.Tensor): with shape (B, 2)
                - waypoints (torch.Tensor): with shape (B, L, 2)
        """
        B, L, _ = hidden_states.size()
        assert L == self.num_queries, f"Number of queries {L} must be equal to the number of queries {self.num_queries}"
        
        # density map inputs construction
        object_density_inputs = hidden_states[:, :self.num_object_density_queries, :]
        ego_velocity = ego_velocity.unsqueeze(-1).repeat(1, self.num_object_density_queries, 32)
        object_density_inputs = torch.cat([object_density_inputs, ego_velocity], dim=-1)
        
        object_density = self.object_density_head(object_density_inputs)
        
        # junction, stop sign, traffic light inputs construction
        junction = self.junction_head(
            hidden_states[:, self.num_object_density_queries: self.num_object_density_queries+self.num_traffic_rule_queries, :]
            )
        stop_sign = self.stop_sign_head(
            hidden_states[:, self.num_object_density_queries: self.num_object_density_queries+self.num_traffic_rule_queries, :]
            )
        traffic_light = self.traffic_light_head(
            hidden_states[:, self.num_object_density_queries: self.num_object_density_queries+self.num_traffic_rule_queries, :]
            )
        waypoints = self.waypoints_head(
            hidden_states[:, -self.num_waypoints_queries:, :], 
            goal_point
            )
        
        return dict(
            object_density=object_density,
            junction=junction.view(B, -1),
            stop_sign=stop_sign.view(B, -1),
            traffic_light=traffic_light.view(B, -1),
            waypoints=waypoints
        )
    
    def loss(self, hidden_states: torch.Tensor, 
                goal_point: torch.Tensor, 
                ego_velocity: torch.Tensor,
                targets: DataSampleType) -> dict:
        """_summary_

        Args:
            hidden_states (torch.Tensor): (B, L, input_size)
            goal_point (torch.Tensor): (B, 2)
            targets (DataSampleType): 

        Returns:
            dict: _description_
        """
        L = hidden_states.size(1) 
        assert L == self.num_queries, f"Number of queries {L} must be equal to the number of queries {self.num_queries}"
        
        gt_grid_density = torch.stack([sample.gt_grids.density for sample in targets], dim=0)
        B, H, W, C = gt_grid_density.size()
        gt_grid_density = gt_grid_density.view(B, H*W, C)
        
        gt_affected_by_junctions = torch.stack([sample.gt_ego.is_at_junction for sample in targets], dim=0).view(B,-1, 2) # (B, ..., 2)
        gt_affected_by_redlights = torch.stack([sample.gt_ego.affected_by_lights for sample in targets], dim=0).view(B,-1, 2) # (B, ..., 2)
        gt_affected_by_stopsigns = torch.stack([sample.gt_ego.affected_by_stop_sign for sample in targets], dim=0).view(B,-1, 2) # (B, ..., 2)
        gt_ego_future_waypoints = torch.stack([sample.gt_ego.traj.data[..., :2] for sample in targets], dim=0)[:, 1:, :] # (B, 10, 2)
        gt_ego_future_waypoints_masks = torch.stack([sample.gt_ego.traj.mask for sample in targets], dim=0)[:, 1:] # (B, 10)

# density map inputs construction
        object_density_inputs = hidden_states[:, :self.num_object_density_queries, :]
        ego_velocity = ego_velocity.unsqueeze(-1).repeat(1, self.num_object_density_queries, 32)
        object_density_inputs = torch.cat([object_density_inputs, ego_velocity], dim=-1)

        loss_density = self.object_density_head.loss(
            object_density_inputs, 
            gt_grid_density
            )
        loss_junction = self.junction_head.loss(
            hidden_states[:, self.num_object_density_queries: self.num_object_density_queries+self.num_traffic_rule_queries, :], 
            gt_affected_by_junctions
            )
        loss_stop_sign = self.stop_sign_head.loss(
            hidden_states[:, self.num_object_density_queries: self.num_object_density_queries+self.num_traffic_rule_queries, :], 
            gt_affected_by_stopsigns
            )
        loss_traffic_light = self.traffic_light_head.loss(
            hidden_states[:, self.num_object_density_queries: self.num_object_density_queries+self.num_traffic_rule_queries, :], 
            gt_affected_by_redlights
            )
        loss_waypoints = self.waypoints_head.loss(
            hidden_states[:, -self.num_waypoints_queries:, :], 
            goal_point, 
            gt_ego_future_waypoints,
            gt_ego_future_waypoints_masks
            )
        
        loss = dict(
            loss_object_density=loss_density,
            loss_junction=loss_junction,
            loss_stop_sign=loss_stop_sign,
            loss_traffic_light=loss_traffic_light,
            loss_waypoints=loss_waypoints
            )
        
        return loss
    
    def predict(self, hidden_states: torch.Tensor, 
                goal_point: torch.Tensor,
                ego_velocity: torch.Tensor) -> dict:
        """
        Args:
            hidden_states (torch.Tensor): with shape (B, L, input_size)
            goal_point (torch.Tensor): with shape (B, 2)

        Returns:
            dict: with keys:
                - object_density (torch.Tensor): with shape (B, L, 7)
                - junction (torch.Tensor): with shape (B, 2)
                - stop_sign (torch.Tensor): with shape (B, 2)
                - traffic_light (torch.Tensor): with shape (B, 2)
                - waypoints (torch.Tensor): with shape (B, L, 2)
        """
        return self(hidden_states, goal_point, ego_velocity)