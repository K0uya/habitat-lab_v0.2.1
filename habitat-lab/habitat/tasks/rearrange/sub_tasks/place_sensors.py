#!/usr/bin/env python3

# Copyright (c) Meta Platforms, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.


from habitat.core.embodied_task import Measure
from habitat.core.registry import registry
from habitat.tasks.rearrange.rearrange_sensors import (
    EndEffectorToGoalDistance,
    EndEffectorToRestDistance,
    ForceTerminate,
    ObjAtGoal,
    ObjectToGoalDistance,
    RearrangeReward,
    RobotForce,
)
from habitat.tasks.rearrange.utils import rearrange_logger


@registry.register_measure
class PlaceReward(RearrangeReward):
    cls_uuid: str = "place_reward"

    def __init__(self, *args, sim, config, task, **kwargs):
        self._prev_dist = -1.0
        self._prev_dropped = False
        self._metric = None
        self._use_ee_dist = config.use_ee_dist
        self._min_dist_to_goal = config.min_dist_to_goal
        self._place_reward = config.place_reward
        self._drop_pen = config.drop_pen
        self._wrong_drop_should_end = config.wrong_drop_should_end
        self._use_diff = config.use_diff
        self._dist_reward = config.dist_reward
        self._sparse_reward = config.sparse_reward
        self._drop_pen_type = getattr(config, "drop_pen_type", "constant")
        self._curr_step = 0
        self._ee_resting_success_threshold = (
            config.ee_resting_success_threshold
        )
        super().__init__(*args, sim=sim, config=config, task=task, **kwargs)

    @staticmethod
    def _get_uuid(*args, **kwargs):
        return PlaceReward.cls_uuid

    @property
    def _ee_to_goal_dist_cls_uuid(self):
        return EndEffectorToGoalDistance.cls_uuid

    @property
    def _obj_to_goal_dist_cls_uuid(self):
        return ObjectToGoalDistance.cls_uuid

    @property
    def _obj_on_goal_cls_uuid(self):
        return ObjAtGoal.cls_uuid

    def reset_metric(self, *args, episode, task, observations, **kwargs):
        task.measurements.check_measure_dependencies(
            self.uuid,
            [
                EndEffectorToRestDistance.cls_uuid,
                RobotForce.cls_uuid,
                ForceTerminate.cls_uuid,
                self._obj_on_goal_cls_uuid,
            ],
        )
        if not self._sparse_reward:
            task.measurements.check_measure_dependencies(
                self.uuid,
                [
                    self._ee_to_goal_dist_cls_uuid,
                    self._obj_to_goal_dist_cls_uuid,
                ],
            )

        self._prev_dist = -1.0
        self._prev_dropped = not self._sim.grasp_mgr.is_grasped
        self._curr_step = 0
        super().reset_metric(
            *args,
            episode=episode,
            task=task,
            observations=observations,
            **kwargs
        )

    def update_metric(self, *args, episode, task, observations, **kwargs):
        super().update_metric(
            *args,
            episode=episode,
            task=task,
            observations=observations,
            **kwargs
        )
        reward = self._metric

        ee_to_rest_distance = task.measurements.measures[
            EndEffectorToRestDistance.cls_uuid
        ].get_metric()

        picked_idx = task._picked_object_idx
        obj_at_goal = task.measurements.measures[
            self._obj_on_goal_cls_uuid
        ].get_metric()[str(picked_idx)]

        snapped_id = self._sim.grasp_mgr.snap_idx
        cur_picked = snapped_id is not None
        if (not obj_at_goal) or cur_picked:
            # First stage reward, if holding object or object is not at goal,
            # agent gets rewarded if distance to goal is greater than min_dist_to_goal
            if self._sparse_reward:
                dist_to_goal = 0.0  # still use dense reward for returning to resting position
            elif self._use_ee_dist:
                ee_to_goal_dist = task.measurements.measures[
                    self._ee_to_goal_dist_cls_uuid
                ].get_metric()
                dist_to_goal = ee_to_goal_dist[str(picked_idx)]
            else:
                obj_to_goal_dist = task.measurements.measures[
                    self._obj_to_goal_dist_cls_uuid
                ].get_metric()
                dist_to_goal = obj_to_goal_dist[str(picked_idx)]
            min_dist = self._min_dist_to_goal
        else:
            # Second stage reward, if object is at goal and the agent has released the object
            # agent is rewarded for returning to resting position
            dist_to_goal = ee_to_rest_distance
            min_dist = self._ee_resting_success_threshold

        # Penalize and end the episode if object is dropped but not on goal, if object is on goal reward the agent
        if (not self._prev_dropped) and (not cur_picked):
            self._prev_dropped = True
            if obj_at_goal:
                reward += self._place_reward
                # If we just transitioned to the next stage our current
                # distance is stale.
                self._prev_dist = -1
            else:
                # Dropped at wrong location
                drop_pen = self._drop_pen
                if self._drop_pen_type == "penalize_remaining_dist":
                    drop_pen *= dist_to_goal
                elif self._drop_pen_type == "penalize_remaining_time":
                    drop_pen *= (300 - self._curr_step) / 300
                reward -= drop_pen
                if self._wrong_drop_should_end:
                    rearrange_logger.debug(
                        "Dropped to wrong place, ending episode."
                    )
                    self._task.should_end = True
                    self._metric = reward
                    return

        # Reward the agent based on distance to goal/resting position
        if dist_to_goal >= min_dist:
            if self._use_diff:
                if self._prev_dist < 0:
                    dist_diff = 0.0
                else:
                    dist_diff = self._prev_dist - dist_to_goal

                # Filter out the small fluctuations
                dist_diff = round(dist_diff, 3)
                reward += self._dist_reward * dist_diff
            else:
                reward -= self._dist_reward * dist_to_goal
        self._prev_dist = dist_to_goal
        self._curr_step += 1

        self._metric = reward


@registry.register_measure
class PlacementStability(Measure):
    cls_uuid: str = "placement_stability"

    def __init__(self, sim, config, *args, **kwargs):
        self._config = config
        self._stability_steps = config.stability_steps
        self._sim = sim
        self._curr_stability_steps = 0
        super().__init__(**kwargs)

    @staticmethod
    def _get_uuid(*args, **kwargs):
        return PlacementStability.cls_uuid

    @property
    def _obj_on_goal_cls_uuid(self):
        return ObjAtGoal.cls_uuid

    def reset_metric(self, *args, episode, task, observations, **kwargs):
        self._curr_stability_steps = 0
        task.measurements.check_measure_dependencies(
            self.uuid,
            [
                self._obj_on_goal_cls_uuid,
            ],
        )
        self.update_metric(
            *args,
            episode=episode,
            task=task,
            observations=observations,
            **kwargs
        )

    def update_metric(self, *args, episode, task, observations, **kwargs):
        picked_idx = task._picked_object_idx
        is_obj_at_goal = task.measurements.measures[
            self._obj_on_goal_cls_uuid
        ].get_metric()[str(picked_idx)]

        is_holding = self._sim.grasp_mgr.is_grasped
        if is_obj_at_goal and not is_holding:
            self._curr_stability_steps += 1  # increment
        else:
            self._curr_stability_steps = 0  # reset
        # if the object remained stable for the required number of steps, then the placement is stable
        self._metric = self._curr_stability_steps >= self._stability_steps


@registry.register_measure
class PlaceSuccess(Measure):
    cls_uuid: str = "place_success"

    def __init__(self, sim, config, *args, **kwargs):
        self._config = config
        self._ee_resting_success_threshold = (
            self._config.ee_resting_success_threshold
        )
        self._check_stability = self._config.check_stability
        self._sim = sim
        super().__init__(**kwargs)

    @staticmethod
    def _get_uuid(*args, **kwargs):
        return PlaceSuccess.cls_uuid

    @property
    def _obj_on_goal_cls_uuid(self):
        return ObjAtGoal.cls_uuid

    @property
    def _placement_stability_cls_uuid(self):
        return PlacementStability.cls_uuid

    def reset_metric(self, *args, episode, task, observations, **kwargs):
        task.measurements.check_measure_dependencies(
            self.uuid,
            [
                EndEffectorToRestDistance.cls_uuid,
                self._obj_on_goal_cls_uuid,
            ],
        )

        if self._check_stability:
            task.measurements.check_measure_dependencies(
                self.uuid,
                [
                    self._placement_stability_cls_uuid,
                ],
            )
        self.update_metric(
            *args,
            episode=episode,
            task=task,
            observations=observations,
            **kwargs
        )

    def update_metric(self, *args, episode, task, observations, **kwargs):
        picked_idx = task._picked_object_idx
        is_obj_at_goal = task.measurements.measures[
            self._obj_on_goal_cls_uuid
        ].get_metric()[str(picked_idx)]
        is_holding = self._sim.grasp_mgr.is_grasped
        is_stable = True
        if self._check_stability:
            is_stable = task.measurements.measures[
                self._placement_stability_cls_uuid
            ].get_metric()
        ee_to_rest_distance = task.measurements.measures[
            EndEffectorToRestDistance.cls_uuid
        ].get_metric()

        self._metric = (
            not is_holding
            and is_obj_at_goal
            and ee_to_rest_distance < self._ee_resting_success_threshold
            and is_stable
        )
