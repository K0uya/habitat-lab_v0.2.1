#!/usr/bin/env python3

# Copyright (c) Meta Platforms, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.


import magnum as mn

from habitat.core.dataset import Episode
from habitat.core.registry import registry
from habitat.tasks.rearrange.sub_tasks.pick_task import RearrangePickTaskV1
from habitat.utils.geometry_utils import quat_to_euler


@registry.register_task(name="RearrangePlaceTask-v0")
class RearrangePlaceTaskV1(RearrangePickTaskV1):
    def _get_targ_pos(self, sim):
        return sim.get_targets()[1]

    def _should_prevent_grip(self, action_args):
        # Never allow regrasping
        return (
            not self._sim.grasp_mgr.is_grasped
            and action_args.get("grip_action", None) is not None
            and action_args["grip_action"] >= 0
        )

    def get_object_pose_by_id(self, obj_idx):
        """Get the object euler angles for a given object index."""
        # Get the object transformation
        rom = self._sim.get_rigid_object_manager()
        obj_transform = rom.get_object_by_id(obj_idx).transformation
        base_transform = self._sim.get_agent_data(
            None
        ).articulated_agent.base_transformation
        # Get the local ee location (x,y,z)
        local_obj_transform = base_transform.inverted() @ obj_transform
        local_obj_quat = mn.Quaternion.from_matrix(
            local_obj_transform.rotation()
        )
        local_obj_euler = quat_to_euler(
            (
                local_obj_quat.scalar,
                local_obj_quat.vector[0],
                local_obj_quat.vector[2],
                local_obj_quat.vector[1],
            )
        )
        return local_obj_euler

    def reset(self, episode: Episode):
        sim = self._sim
        # Remove whatever the agent is currently holding.
        sim.grasp_mgr.desnap(force=True)

        super().reset(episode, fetch_observations=False)

        abs_obj_idx = sim.scene_obj_ids[self.abs_targ_idx]

        # Get the initial object orientation
        # This is the object orientation (in ee frame) at grasping moment
        # We will like the robot to match such init_obj_orientation when dropping the object
        # The sensor will be relative orientation to the initial object orientation
        self.init_obj_orientation = self.get_object_pose_by_id(abs_obj_idx)

        # Here, we teleport the target object to the gripper
        # The place task is to let Spot place the object in the original
        # object location
        sim.grasp_mgr.snap_to_obj(abs_obj_idx, force=True)

        # For the gripper to enforce the initial object orientation

        self.was_prev_holding = self.targ_idx

        sim.internal_step(-1)
        self._sim.maybe_update_articulated_agent()

        # Get the initial EE orientation at the time of begining of placing
        _, self.init_ee_orientation = self._sim.get_agent_data(
            None
        ).articulated_agent.get_ee_local_pose()  # type: ignore

        return self._get_observations(episode)
