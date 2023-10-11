#!/usr/bin/env python3

# Copyright (c) Meta Platforms, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import magnum as mn
import numpy as np
from gym import spaces

import habitat_sim
from habitat.core.embodied_task import Measure
from habitat.core.registry import registry
from habitat.core.simulator import Sensor, SensorTypes
from habitat.tasks.rearrange.rearrange_sensors import (
    DoesWantTerminate,
    RearrangeReward,
)
from habitat.tasks.rearrange.utils import UsesArticulatedAgentInterface
from habitat.tasks.utils import cartesian_to_polar

BASE_ACTION_NAME = "base_velocity"


@registry.register_sensor
class NavGoalPointGoalSensor(UsesArticulatedAgentInterface, Sensor):
    """
    GPS and compass sensor relative to the starting object position or goal
    position.
    """

    cls_uuid: str = "goal_to_agent_gps_compass"

    def __init__(self, *args, sim, task, **kwargs):
        self._task = task
        self._sim = sim
        super().__init__(*args, task=task, **kwargs)
        self._goal_is_human = kwargs["config"]["goal_is_human"]
        self._human_agent_idx = kwargs["config"]["human_agent_idx"]

    def _get_uuid(self, *args, **kwargs):
        return NavGoalPointGoalSensor.cls_uuid

    def _get_sensor_type(self, *args, **kwargs):
        return SensorTypes.TENSOR

    def _get_observation_space(self, *args, config, **kwargs):
        return spaces.Box(
            shape=(2,),
            low=np.finfo(np.float32).min,
            high=np.finfo(np.float32).max,
            dtype=np.float32,
        )

    def get_observation(self, task, *args, **kwargs):
        articulated_agent_T = self._sim.get_agent_data(
            self.agent_id
        ).articulated_agent.base_transformation
        # Make the goal to be the human location
        if self._goal_is_human:
            human_pos = self._sim.get_agent_data(
                self._human_agent_idx
            ).articulated_agent.base_pos
            task.nav_goal_pos = np.array(human_pos)

        dir_vector = articulated_agent_T.inverted().transform_point(
            task.nav_goal_pos
        )

        rho, phi = cartesian_to_polar(dir_vector[0], dir_vector[1])
        return np.array([rho, -phi], dtype=np.float32)


@registry.register_sensor
class OracleNavigationActionSensor(Sensor):
    cls_uuid: str = "oracle_nav_actions"

    def __init__(self, sim, config, *args, **kwargs):
        super().__init__(config=config)
        self._sim = sim

    def _get_uuid(self, *args, **kwargs):
        return OracleNavigationActionSensor.cls_uuid

    def _get_sensor_type(self, *args, **kwargs):
        return SensorTypes.TENSOR

    def _get_observation_space(self, *args, config, **kwargs):
        return spaces.Box(
            shape=(3,),
            low=np.finfo(np.float32).min,
            high=np.finfo(np.float32).max,
            dtype=np.float32,
        )

    def _path_to_point(self, point):
        agent_pos = self._sim.articulated_agent.base_pos

        path = habitat_sim.ShortestPath()
        path.requested_start = agent_pos
        path.requested_end = point
        found_path = self._sim.pathfinder.find_path(path)
        if not found_path:
            return [agent_pos, point]
        return path.points

    def get_observation(self, task, *args, **kwargs):
        path = self._path_to_point(task.nav_target_pos)
        return path[1]


@registry.register_measure
class NavToObjReward(RearrangeReward):
    cls_uuid: str = "nav_to_obj_reward"

    @staticmethod
    def _get_uuid(*args, **kwargs):
        return NavToObjReward.cls_uuid

    def reset_metric(self, *args, episode, task, observations, **kwargs):
        task.measurements.check_measure_dependencies(
            self.uuid,
            [
                NavToObjSuccess.cls_uuid,
                DistToGoal.cls_uuid,
                RotDistToGoal.cls_uuid,
            ],
        )
        self._cur_angle_dist = -1.0
        self._prev_dist = -1.0
        super().reset_metric(
            *args,
            episode=episode,
            task=task,
            observations=observations,
            **kwargs,
        )

    def update_metric(self, *args, episode, task, observations, **kwargs):
        reward = 0.0
        cur_dist = task.measurements.measures[DistToGoal.cls_uuid].get_metric()
        if self._prev_dist < 0.0:
            dist_diff = 0.0
        else:
            dist_diff = self._prev_dist - cur_dist

        reward += self._config.dist_reward * dist_diff
        self._prev_dist = cur_dist

        if (
            self._config.should_reward_turn
            and cur_dist < self._config.turn_reward_dist
        ):
            angle_dist = task.measurements.measures[
                RotDistToGoal.cls_uuid
            ].get_metric()

            if self._cur_angle_dist < 0:
                angle_diff = 0.0
            else:
                angle_diff = self._cur_angle_dist - angle_dist

            reward += self._config.angle_dist_reward * angle_diff
            self._cur_angle_dist = angle_dist

        self._metric = reward


@registry.register_measure
class DistToGoal(UsesArticulatedAgentInterface, Measure):
    cls_uuid: str = "dist_to_goal"

    def __init__(self, *args, sim, config, task, **kwargs):
        self._config = config
        self._sim = sim
        self._prev_dist = None
        super().__init__(*args, sim=sim, config=config, task=task, **kwargs)

    def reset_metric(self, *args, episode, task, observations, **kwargs):
        self._prev_dist = self._get_cur_geo_dist(task)
        self.update_metric(
            *args,
            episode=episode,
            task=task,
            observations=observations,
            **kwargs,
        )

    def _get_cur_geo_dist(self, task):
        return np.linalg.norm(
            np.array(
                self._sim.get_agent_data(
                    self.agent_id
                ).articulated_agent.base_pos
            )[[0, 2]]
            - task.nav_goal_pos[[0, 2]]
        )

    @staticmethod
    def _get_uuid(*args, **kwargs):
        return DistToGoal.cls_uuid

    def update_metric(self, *args, episode, task, observations, **kwargs):
        self._metric = self._get_cur_geo_dist(task)


@registry.register_measure
class RotDistToGoal(UsesArticulatedAgentInterface, Measure):
    cls_uuid: str = "rot_dist_to_goal"

    def __init__(self, *args, sim, **kwargs):
        self._sim = sim
        super().__init__(*args, sim=sim, **kwargs)

    @staticmethod
    def _get_uuid(*args, **kwargs):
        return RotDistToGoal.cls_uuid

    def reset_metric(self, *args, **kwargs):
        self.update_metric(
            *args,
            **kwargs,
        )

    def update_metric(self, *args, episode, task, observations, **kwargs):
        targ = task.nav_goal_pos
        # Get the agent
        robot = self._sim.get_agent_data(self.agent_id).articulated_agent
        # Get the base transformation
        T = robot.base_transformation
        # Do transformation
        pos = T.inverted().transform_point(targ)
        # Project to 2D plane (x,y,z=0)
        pos[2] = 0.0
        # Unit vector of the pos
        pos = pos.normalized()
        # Define the coordinate of the robot
        pos_robot = np.array([1.0, 0.0, 0.0])
        # Get the angle
        angle = np.arccos(np.dot(pos, pos_robot))
        self._metric = np.abs(float(angle))


@registry.register_measure
class NavToPosSucc(Measure):
    cls_uuid: str = "nav_to_pos_success"

    @staticmethod
    def _get_uuid(*args, **kwargs):
        return NavToPosSucc.cls_uuid

    def __init__(self, *args, config, **kwargs):
        self._config = config
        super().__init__(*args, config=config, **kwargs)

    def reset_metric(self, *args, task, **kwargs):
        task.measurements.check_measure_dependencies(
            self.uuid,
            [DistToGoal.cls_uuid],
        )
        self.update_metric(*args, task=task, **kwargs)

    def update_metric(self, *args, episode, task, observations, **kwargs):
        dist = task.measurements.measures[DistToGoal.cls_uuid].get_metric()
        self._metric = dist < self._config.success_distance


@registry.register_measure
class NavToObjSuccess(Measure):
    cls_uuid: str = "nav_to_obj_success"

    @staticmethod
    def _get_uuid(*args, **kwargs):
        return NavToObjSuccess.cls_uuid

    def reset_metric(self, *args, task, **kwargs):
        task.measurements.check_measure_dependencies(
            self.uuid,
            [NavToPosSucc.cls_uuid, RotDistToGoal.cls_uuid],
        )
        self.update_metric(*args, task=task, **kwargs)

    def __init__(self, *args, config, **kwargs):
        self._config = config
        super().__init__(*args, config=config, **kwargs)

    def update_metric(self, *args, episode, task, observations, **kwargs):
        angle_dist = task.measurements.measures[
            RotDistToGoal.cls_uuid
        ].get_metric()

        nav_pos_succ = task.measurements.measures[
            NavToPosSucc.cls_uuid
        ].get_metric()

        called_stop = task.measurements.measures[
            DoesWantTerminate.cls_uuid
        ].get_metric()

        if self._config.must_look_at_targ:
            self._metric = (
                nav_pos_succ and angle_dist < self._config.success_angle_dist
            )
        else:
            self._metric = nav_pos_succ

        if self._config.must_call_stop:
            if called_stop:
                task.should_end = True
            else:
                self._metric = False


@registry.register_measure
class SocialNavReward(UsesArticulatedAgentInterface, Measure):
    """
    Reward that gives a continuous reward for the social navigation task.
    """

    cls_uuid: str = "social_nav_reward"

    @staticmethod
    def _get_uuid(*args, **kwargs):
        return SocialNavReward.cls_uuid

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = kwargs["config"]
        # Get the config and setup the hyperparameters
        self._config = config
        self._sim = kwargs["sim"]
        self._safe_dis_min = config.safe_dis_min
        self._safe_dis_max = config.safe_dis_max
        self._safe_dis_reward = config.safe_dis_reward
        self._facing_human_dis = config.facing_human_dis
        self._facing_human_reward = config.facing_human_reward
        self._use_geo_distance = config.use_geo_distance
        # Record the previous distance to human
        self._prev_dist = -1.0
        self._robot_idx = config.robot_idx
        self._human_idx = config.human_idx

    def reset_metric(self, *args, **kwargs):
        self.update_metric(
            *args,
            **kwargs,
        )
        self._prev_dist = -1.0

    def update_metric(self, *args, episode, task, observations, **kwargs):
        self._metric = 0.0

        # Get the pos
        use_k_human = f"agent_{self._human_idx}_localization_sensor"
        human_pos = observations[use_k_human][:3]
        use_k_robot = f"agent_{self._robot_idx}_localization_sensor"
        robot_pos = observations[use_k_robot][:3]

        # If we consider using geo distance
        if self._use_geo_distance:
            path = habitat_sim.ShortestPath()
            path.requested_start = np.array(robot_pos)
            path.requested_end = human_pos
            found_path = self._sim.pathfinder.find_path(path)

        # Compute the distance between the robot and the human
        if self._use_geo_distance and found_path:
            dis = self._sim.geodesic_distance(robot_pos, human_pos)
        else:
            dis = np.linalg.norm(human_pos - robot_pos)

        # Social nav reward three stage design
        if dis >= self._safe_dis_min and dis < self._safe_dis_max:
            # If the distance is within the safety interval
            self._metric = self._safe_dis_reward
        elif dis < self._safe_dis_min:
            # If the distance is too samll
            self._metric = dis - self._prev_dist
        else:
            # if the distance is too large
            self._metric = self._prev_dist - dis

        # Social nav reward for facing human
        if dis < self._facing_human_dis and self._facing_human_reward != -1:
            # Compute the vector from robot to human
            vector_human_robot = human_pos - robot_pos
            # Normalization
            vector_human_robot = vector_human_robot / np.linalg.norm(
                vector_human_robot
            )
            # Compute robot forward vector
            base_T = self._sim.get_agent_data(
                self.agent_id
            ).articulated_agent.base_transformation
            forward_robot = base_T.transform_vector(mn.Vector3(1, 0, 0))
            # Dot product
            self._metric += self._facing_human_reward * np.dot(
                forward_robot.normalized(), vector_human_robot
            )

        if self._prev_dist < 0:
            self._metric = 0.0

        # Update the distance
        self._prev_dist = dis  # type: ignore


@registry.register_measure
class SocialNavStats(UsesArticulatedAgentInterface, Measure):
    """
    The measure for social navigation
    """

    cls_uuid: str = "social_nav_stats"

    def __init__(self, sim, config, *args, **kwargs):
        super().__init__(**kwargs)
        self._sim = sim
        self._config = config

        # Hyper-parameters
        self._check_human_in_frame = self._config.check_human_in_frame
        self._min_dis_human = self._config.min_dis_human
        self._max_dis_human = self._config.max_dis_human
        self._human_id = self._config.human_id
        self._human_detect_threshold = (
            self._config.human_detect_pixel_threshold
        )
        self._total_step = self._config.total_steps
        self._dis_threshold_for_backup_yield = (
            self._config.dis_threshold_for_backup_yield
        )
        self._min_abs_vel_for_yield = self._config.min_abs_vel_for_yield
        self._robot_face_human_threshold = (
            self._config.robot_face_human_threshold
        )
        self._enable_shortest_path_computation = (
            self._config.enable_shortest_path_computation
        )
        self._robot_idx = config.robot_idx
        self._human_idx = config.human_idx

        # For the variable tracking
        self._val_dict = {
            "min_start_end_episode_step": float("inf"),
            "has_found_human": False,
            "has_found_human_step": self._total_step,
            "found_human_times": 0,
            "after_found_human_times": 0,
            "step": 0,
            "step_after_found": 1,
            "dis": 0,
            "dis_after_found": 0,
            "backup_count": 0,
            "yield_count": 0,
        }

        # Robot's info
        self._prev_robot_base_T = None
        self._robot_init_pos = None
        self._robot_init_trans = None

        # Store pos of human and robot
        self.human_pos_list = []
        self.robot_pos_list = []

    @staticmethod
    def _get_uuid(*args, **kwargs):
        return SocialNavStats.cls_uuid

    def reset_metric(self, *args, task, **kwargs):
        robot_pos = np.array(
            self._sim.get_agent_data(self.agent_id).articulated_agent.base_pos
        )

        # For the variable track
        self._val_dict = {
            "min_start_end_episode_step": float("inf"),
            "has_found_human": False,
            "has_found_human_step": 1500,
            "found_human_times": 0,
            "after_found_human_times": 0,
            "step": 0,
            "step_after_found": 1,
            "dis": 0,
            "dis_after_found": 0,
            "backup_count": 0,
            "yield_count": 0,
        }

        # Robot's info
        self._robot_init_pos = robot_pos
        self._robot_init_trans = mn.Matrix4(
            self._sim.get_agent_data(
                0
            ).articulated_agent.sim_obj.transformation
        )

        self._prev_robot_base_T = mn.Matrix4(
            self._sim.get_agent_data(
                0
            ).articulated_agent.sim_obj.transformation
        )

        # Store pos of human and robot
        self.human_pos_list = []
        self.robot_pos_list = []

        # Update metrics
        self.update_metric(*args, task=task, **kwargs)

    def _check_human_dis(self, robot_pos, human_pos):
        # We use geo geodesic distance here
        dis = self._sim.geodesic_distance(robot_pos, human_pos)
        return dis >= self._min_dis_human and dis <= self._max_dis_human

    def _check_human_frame(self, obs):
        if not self._check_human_in_frame:
            return True
        use_k = f"agent_{self._robot_idx}_articulated_agent_arm_panoptic"
        panoptic = obs[use_k]
        return (
            np.sum(panoptic == self._human_id) > self._human_detect_threshold
        )

    def _check_robot_facing_human(self, human_pos, robot_pos):
        vector_human_robot = human_pos - robot_pos
        vector_human_robot = vector_human_robot / np.linalg.norm(
            vector_human_robot
        )
        base_T = self._sim.get_agent_data(
            0
        ).articulated_agent.sim_obj.transformation
        forward_robot = base_T.transform_vector(mn.Vector3(1, 0, 0))
        facing = (
            np.dot(forward_robot.normalized(), vector_human_robot)
            > self._robot_face_human_threshold
        )
        return facing

    def update_metric(self, *args, episode, task, observations, **kwargs):
        # Get the agent locations
        robot_pos = np.array(
            self._sim.get_agent_data(
                self._robot_idx
            ).articulated_agent.base_pos
        )
        human_pos = np.array(
            self._sim.get_agent_data(
                self._human_idx
            ).articulated_agent.base_pos
        )

        # Store the human/robot position info
        self.human_pos_list.append(human_pos)
        self.robot_pos_list.append(robot_pos)

        # Compute the distance based on the L2 norm
        dis = np.linalg.norm(robot_pos - human_pos, ord=2, axis=-1)

        # Add the current distance to compute average distance
        self._val_dict["dis"] += dis

        # Compute the robot moving velocity for backup and yiled metrics
        robot_move_vec = np.array(
            self._prev_robot_base_T.inverted().transform_point(robot_pos)
        )[[0, 2]]
        robot_move_vel = (
            np.linalg.norm(robot_move_vec)
            / (1.0 / 120.0)
            * np.sign(robot_move_vec[0])
        )

        # Compute the metrics for backing up and yield
        if (
            dis <= self._dis_threshold_for_backup_yield
            and robot_move_vel < 0.0
        ):
            self._val_dict["backup_count"] += 1
        elif (
            dis <= self._dis_threshold_for_backup_yield
            and abs(robot_move_vel) < self._min_abs_vel_for_yield
        ):
            self._val_dict["yield_count"] += 1

        # Increase the step counter
        self._val_dict["step"] += 1

        # Check if human has been found
        found_human = False
        if self._check_human_dis(
            robot_pos, human_pos
        ) and self._check_robot_facing_human(human_pos, robot_pos):
            found_human = True
            self._val_dict["has_found_human"] = True
            self._val_dict["found_human_times"] += 1

        # Compute the metrics after finding the human
        if self._val_dict["has_found_human"]:
            self._val_dict["dis_after_found"] += dis
            self._val_dict["after_found_human_times"] += found_human

        # Record the step taken to find the human
        if (
            self._val_dict["has_found_human"]
            and self._val_dict["has_found_human_step"] == 1500
        ):
            self._val_dict["has_found_human_step"] = self._val_dict["step"]

        # Compute the minimum distance only when the minimum distance has not found yet
        if (
            self._val_dict["min_start_end_episode_step"] == float("inf")
            and self._enable_shortest_path_computation
        ):
            use_k_human = (
                f"agent_{self._human_idx}_oracle_nav_randcoord_action"
            )
            robot_to_human_min_step = task.actions[
                use_k_human
            ]._compute_robot_to_human_min_step(
                self._robot_init_trans, human_pos, self.human_pos_list
            )

            if robot_to_human_min_step <= self._val_dict["step"]:
                robot_to_human_min_step = self._val_dict["step"]
            else:
                robot_to_human_min_step = float("inf")

            # Update the minimum SPL
            self._val_dict["min_start_end_episode_step"] = min(
                self._val_dict["min_start_end_episode_step"],
                robot_to_human_min_step,
            )

        # Compute the SPL before finding the human
        first_encounter_spl = (
            self._val_dict["has_found_human"]
            * self._val_dict["min_start_end_episode_step"]
            / max(
                self._val_dict["min_start_end_episode_step"],
                self._val_dict["has_found_human_step"],
            )
        )

        # Make sure the first_encounter_spl is not NaN
        if np.isnan(first_encounter_spl):
            first_encounter_spl = 0.0

        self._prev_robot_base_T = mn.Matrix4(
            self._sim.get_agent_data(
                0
            ).articulated_agent.sim_obj.transformation
        )

        # Compute the metrics
        self._metric = {
            "has_found_human": self._val_dict["has_found_human"],
            "found_human_rate_over_epi": self._val_dict["found_human_times"]
            / self._val_dict["step"],
            "found_human_rate_after_encounter_over_epi": self._val_dict[
                "after_found_human_times"
            ]
            / self._val_dict["step_after_found"],
            "avg_robot_to_human_dis_over_epi": self._val_dict["dis"]
            / self._val_dict["step"],
            "avg_robot_to_human_after_encounter_dis_over_epi": self._val_dict[
                "dis_after_found"
            ]
            / self._val_dict["step_after_found"],
            "first_encounter_spl": first_encounter_spl,
            "frist_ecnounter_steps": self._val_dict["has_found_human_step"],
            "frist_ecnounter_steps_ratio": self._val_dict[
                "has_found_human_step"
            ]
            / self._val_dict["min_start_end_episode_step"],
            "follow_human_steps_after_frist_encounter": self._val_dict[
                "after_found_human_times"
            ],
            "follow_human_steps_ratio_after_frist_encounter": self._val_dict[
                "after_found_human_times"
            ]
            / (
                self._total_step - self._val_dict["min_start_end_episode_step"]
            ),
            "backup_ratio": self._val_dict["backup_count"]
            / self._val_dict["step"],
            "yield_ratio": self._val_dict["yield_count"]
            / self._val_dict["step"],
        }

        # Update the counter
        if self._val_dict["has_found_human"]:
            self._val_dict["step_after_found"] += 1


@registry.register_measure
class SocialNavSeekSuccess(Measure):
    """Social nav seek success meassurement"""

    cls_uuid: str = "nav_seek_success"

    @staticmethod
    def _get_uuid(*args, **kwargs):
        return SocialNavSeekSuccess.cls_uuid

    def reset_metric(self, *args, task, **kwargs):
        """Reset the metrics"""
        task.measurements.check_measure_dependencies(
            self.uuid,
            [NavToPosSucc.cls_uuid, RotDistToGoal.cls_uuid],
        )
        self._following_step = 0
        self.update_metric(*args, task=task, **kwargs)

    def __init__(self, *args, config, sim, **kwargs):
        self._config = config
        self._sim = sim

        super().__init__(*args, config=config, **kwargs)
        # Setup the parameters
        self._following_step = 0
        self._following_step_succ_threshold = (
            config.following_step_succ_threshold
        )
        self._safe_dis_min = config.safe_dis_min
        self._safe_dis_max = config.safe_dis_max
        self._use_geo_distance = config.use_geo_distance
        self._need_to_face_human = config.need_to_face_human
        self._facing_threshold = config.facing_threshold
        self._robot_idx = config.robot_idx
        self._human_idx = config.human_idx

    def update_metric(self, *args, episode, task, observations, **kwargs):
        # Get the angle distance
        angle_dist = task.measurements.measures[
            RotDistToGoal.cls_uuid
        ].get_metric()

        # Get the positions of the human and the robot
        use_k_human = f"agent_{self._human_idx}_localization_sensor"
        human_pos = observations[use_k_human][:3]
        use_k_robot = f"agent_{self._robot_idx}_localization_sensor"
        robot_pos = observations[use_k_robot][:3]

        # If we want to use the geo distance
        if self._use_geo_distance:
            dist = self._sim.geodesic_distance(robot_pos, human_pos)
        else:
            dist = task.measurements.measures[DistToGoal.cls_uuid].get_metric()

        # Compute facing to human
        vector_human_robot = human_pos - robot_pos
        vector_human_robot = vector_human_robot / np.linalg.norm(
            vector_human_robot
        )
        base_T = self._sim.get_agent_data(
            0
        ).articulated_agent.base_transformation
        forward_robot = base_T.transform_vector(mn.Vector3(1, 0, 0))
        facing = (
            np.dot(forward_robot.normalized(), vector_human_robot)
            > self._facing_threshold
        )

        # Check if the agent follows the human within the safe distance
        if (
            dist >= self._safe_dis_min
            and dist < self._safe_dis_max
            and self._need_to_face_human
            and facing
        ):
            self._following_step += 1

        nav_pos_succ = False
        if self._following_step >= self._following_step_succ_threshold:
            nav_pos_succ = True

        # If the robot needs to look at the target
        if self._config.must_look_at_targ:
            self._metric = (
                nav_pos_succ and angle_dist < self._config.success_angle_dist
            )
        else:
            self._metric = nav_pos_succ
