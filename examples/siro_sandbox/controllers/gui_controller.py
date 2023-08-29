#!/usr/bin/env python3

# Copyright (c) Meta Platforms, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from typing import Any

import magnum as mn
import numpy as np

from habitat.articulated_agent_controllers import HumanoidRearrangeController
from habitat.gui.gui_input import GuiInput
from habitat.tasks.rearrange.actions.actions import ArmEEAction
from habitat.tasks.rearrange.utils import get_aabb
from habitat_sim.physics import (
    CollisionGroupHelper,
    CollisionGroups,
    MotionType,
)

from .controller_abc import GuiController


class GuiRobotController(GuiController):
    """Controller for robot agent."""

    def act(self, obs, env):
        if self._is_multi_agent:
            agent_k = f"agent_{self._agent_idx}_"
        else:
            agent_k = ""
        arm_k = f"{agent_k}arm_action"
        grip_k = f"{agent_k}grip_action"
        base_k = f"{agent_k}base_vel"
        arm_name = f"{agent_k}arm_action"
        base_name = f"{agent_k}base_velocity"
        ac_spaces = env.action_space.spaces

        if arm_name in ac_spaces:
            arm_action_space = ac_spaces[arm_name][arm_k]
            arm_ctrlr = env.task.actions[arm_name].arm_ctrlr
            arm_action = np.zeros(arm_action_space.shape[0])
            grasp = 0
        else:
            arm_ctrlr = None
            arm_action = None
            grasp = None

        base_action: Any = None
        if base_name in ac_spaces:
            base_action_space = ac_spaces[base_name][base_k]
            base_action = np.zeros(base_action_space.shape[0])
        else:
            base_action = None

        KeyNS = GuiInput.KeyNS
        gui_input = self._gui_input

        if base_action is not None:
            # Base control
            base_action = [0, 0]
            if gui_input.get_key(KeyNS.J):
                # Left
                base_action[1] += 1
            if gui_input.get_key(KeyNS.L):
                # Right
                base_action[1] -= 1
            if gui_input.get_key(KeyNS.K):
                # Back
                base_action[0] -= 1
            if gui_input.get_key(KeyNS.I):
                # Forward
                base_action[0] += 1

        if isinstance(arm_ctrlr, ArmEEAction):
            EE_FACTOR = 0.5
            # End effector control
            if gui_input.get_key_down(KeyNS.D):
                arm_action[1] -= EE_FACTOR
            elif gui_input.get_key_down(KeyNS.A):
                arm_action[1] += EE_FACTOR
            elif gui_input.get_key_down(KeyNS.W):
                arm_action[0] += EE_FACTOR
            elif gui_input.get_key_down(KeyNS.S):
                arm_action[0] -= EE_FACTOR
            elif gui_input.get_key_down(KeyNS.Q):
                arm_action[2] += EE_FACTOR
            elif gui_input.get_key_down(KeyNS.E):
                arm_action[2] -= EE_FACTOR
        else:
            # Velocity control. A different key for each joint
            if gui_input.get_key_down(KeyNS.Q):
                arm_action[0] = 1.0
            elif gui_input.get_key_down(KeyNS.ONE):
                arm_action[0] = -1.0

            elif gui_input.get_key_down(KeyNS.W):
                arm_action[1] = 1.0
            elif gui_input.get_key_down(KeyNS.TWO):
                arm_action[1] = -1.0

            elif gui_input.get_key_down(KeyNS.E):
                arm_action[2] = 1.0
            elif gui_input.get_key_down(KeyNS.THREE):
                arm_action[2] = -1.0

            elif gui_input.get_key_down(KeyNS.R):
                arm_action[3] = 1.0
            elif gui_input.get_key_down(KeyNS.FOUR):
                arm_action[3] = -1.0

            elif gui_input.get_key_down(KeyNS.T):
                arm_action[4] = 1.0
            elif gui_input.get_key_down(KeyNS.FIVE):
                arm_action[4] = -1.0

            elif gui_input.get_key_down(KeyNS.Y):
                arm_action[5] = 1.0
            elif gui_input.get_key_down(KeyNS.SIX):
                arm_action[5] = -1.0

            elif gui_input.get_key_down(KeyNS.U):
                arm_action[6] = 1.0
            elif gui_input.get_key_down(KeyNS.SEVEN):
                arm_action[6] = -1.0

        if gui_input.get_key_down(KeyNS.P):
            # logger.info("[play.py]: Unsnapping")
            # Unsnap
            grasp = -1
        elif gui_input.get_key_down(KeyNS.O):
            # Snap
            # logger.info("[play.py]: Snapping")
            grasp = 1

        # reference code
        # if gui_input.get_key_down(KeyNS.PERIOD):
        #     # Print the current position of the robot, useful for debugging.
        #     pos = [
        #         float("%.3f" % x) for x in env._sim.robot.sim_obj.translation
        #     ]
        #     rot = env._sim.robot.sim_obj.rotation
        #     ee_pos = env._sim.robot.ee_transform.translation
        #     logger.info(
        #         f"Robot state: pos = {pos}, rotation = {rot}, ee_pos = {ee_pos}"
        #     )
        # elif gui_input.get_key_down(KeyNS.COMMA):
        #     # Print the current arm state of the robot, useful for debugging.
        #     # joint_state = [
        #     #     float("%.3f" % x) for x in env._sim.robot.arm_joint_pos
        #     # ]

        #     # logger.info(f"Robot arm joint state: {joint_state}")

        action_names = []
        action_args: Any = {}
        if base_action is not None:
            action_names.append(base_name)
            action_args.update(
                {
                    base_k: base_action,
                }
            )
        if arm_action is not None:
            action_names.append(arm_name)
            action_args.update(
                {
                    arm_k: arm_action,
                    grip_k: grasp,
                }
            )
        if len(action_names) == 0:
            raise ValueError("No active actions for human controller.")

        return {"action": action_names, "action_args": action_args}


class GuiHumanoidController(GuiController):
    """Controller for humanoid agent."""

    def __init__(
        self,
        agent_idx,
        is_multi_agent,
        gui_input,
        env,
        walk_pose_path,
        recorder,
    ):
        super().__init__(agent_idx, is_multi_agent, gui_input)
        self._humanoid_controller = HumanoidRearrangeController(walk_pose_path)
        self._env = env
        self._hint_walk_dir = None
        self._hint_grasp_obj_idx = None
        self._hint_drop_pos = None
        self._hint_throw_vel = None
        self._cam_yaw = 0
        self._saved_object_rotation = None
        self._recorder = recorder

        self._thrown_object_collision_group = CollisionGroups.UserGroup7
        self._last_object_thrown_info = None
        self.selected_obj = None

        self.ind = 0

    def get_articulated_agent(self):
        return self._env._sim.agents_mgr[self._agent_idx].articulated_agent

    def on_environment_reset(self):
        super().on_environment_reset()
        base_trans = self.get_articulated_agent().base_transformation
        self._humanoid_controller.reset(base_trans)
        self._hint_walk_dir = None
        self._hint_grasp_obj_idx = None
        self._hint_drop_pos = None
        self._cam_yaw = 0
        self._hint_throw_vel = None
        self._last_object_thrown_info = None

        # Disable collision between thrown object and the agents.
        # Both agents (robot and humanoid) have the collision group Robot.
        CollisionGroupHelper.set_mask_for_group(
            self._thrown_object_collision_group, ~CollisionGroups.Robot
        )
        assert not self.is_grasped

    def get_random_joint_action(self):
        # Add random noise to human arms but keep global transform
        (
            joint_trans,
            root_trans,
        ) = self.get_articulated_agent().get_joint_transform()
        # Divide joint_trans by 4 since joint_trans has flattened quaternions
        # and the dimension of each quaternion is 4
        num_joints = len(joint_trans) // 4
        root_trans = np.array(root_trans)
        index_arms_start = 10
        joint_trans_quat = [
            mn.Quaternion(
                mn.Vector3(joint_trans[(4 * index) : (4 * index + 3)]),
                joint_trans[4 * index + 3],
            )
            for index in range(num_joints)
        ]
        rotated_joints_quat = []
        for index, joint_quat in enumerate(joint_trans_quat):
            random_vec = np.random.rand(3)
            # We allow for maximum 10 angles per step
            random_angle = np.random.rand() * 10
            rotation_quat = mn.Quaternion.rotation(
                mn.Rad(random_angle), mn.Vector3(random_vec).normalized()
            )
            if index > index_arms_start:
                joint_quat *= rotation_quat
            rotated_joints_quat.append(joint_quat)
        joint_trans = np.concatenate(
            [
                np.array(list(quat.vector) + [quat.scalar])
                for quat in rotated_joints_quat
            ]
        )
        humanoidjoint_action = np.concatenate(
            [joint_trans.reshape(-1), root_trans.transpose().reshape(-1)]
        )
        return humanoidjoint_action

    def set_act_hints(
        self, walk_dir, grasp_obj_idx, do_drop, cam_yaw=None, throw_vel=None
    ):
        assert (
            throw_vel is None or do_drop is None
        ), "You can not set throw_velocity and drop_position at the same time"
        self._hint_walk_dir = walk_dir
        self._hint_grasp_obj_idx = grasp_obj_idx
        self._hint_drop_pos = do_drop
        self._cam_yaw = cam_yaw
        self._hint_throw_vel = throw_vel

    def _get_grasp_mgr(self):
        agents_mgr = self._env._sim.agents_mgr
        grasp_mgr = agents_mgr._all_agent_data[self._agent_idx].grasp_mgr
        return grasp_mgr

    @property
    def is_grasped(self):
        return self._get_grasp_mgr().is_grasped

    def _update_grasp(self, grasp_object_id, drop_pos, speed):
        if grasp_object_id is not None:
            assert not self.is_grasped

            sim = self._env.task._sim
            rigid_obj = sim.get_rigid_object_manager().get_object_by_id(
                grasp_object_id
            )
            self._saved_object_rotation = rigid_obj.rotation

            self._get_grasp_mgr().snap_to_obj(grasp_object_id)

            self._recorder.record("grasp_object_id", grasp_object_id)

        elif drop_pos is not None:
            assert self.is_grasped
            grasp_object_id = self._get_grasp_mgr().snap_idx
            self._get_grasp_mgr().desnap()

            # teleport to requested drop_pos
            sim = self._env.task._sim
            rigid_obj = sim.get_rigid_object_manager().get_object_by_id(
                grasp_object_id
            )
            rigid_obj.translation = drop_pos
            rigid_obj.rotation = self._saved_object_rotation
            self._saved_object_rotation = None

            self._recorder.record("drop_pos", drop_pos)

        elif speed is not None:
            grasp_mgr = self._get_grasp_mgr()
            grasp_object_id = grasp_mgr.snap_idx
            grasp_mgr.desnap()
            sim = self._env.task._sim
            rigid_obj = sim.get_rigid_object_manager().get_object_by_id(
                grasp_object_id
            )
            rigid_obj.motion_type = MotionType.DYNAMIC
            rigid_obj.collidable = True
            rigid_obj.override_collision_group(
                self._thrown_object_collision_group
            )
            rigid_obj.linear_velocity = speed
            obj_bb = get_aabb(grasp_object_id, self._env.task._sim)
            self._last_object_thrown_info = (
                rigid_obj,
                max(obj_bb.size_x(), obj_bb.size_y(), obj_bb.size_z()),
            )

        if self._last_object_thrown_info is not None:
            grasp_mgr = self._get_grasp_mgr()

            # when the thrown object leaves the hand, update the collisiongroups
            rigid_obj = self._last_object_thrown_info[0]
            ee_pos = (
                self.get_articulated_agent()
                .ee_transform(grasp_mgr.ee_index)
                .translation
            )
            dist = np.linalg.norm(ee_pos - rigid_obj.translation)
            if dist >= self._last_object_thrown_info[1]:
                rigid_obj.override_collision_group(CollisionGroups.Default)
                self._last_object_thrown_info = None

    def act(self, obs, env):
        self._update_grasp(
            self._hint_grasp_obj_idx,
            self._hint_drop_pos,
            self._hint_throw_vel,
        )
        self._hint_grasp_obj_idx = None
        self._hint_drop_pos = None
        self._hint_throw_vel = None

        KeyNS = GuiInput.KeyNS
        gui_input = self._gui_input

        humancontroller_base_user_input = np.zeros(3)
        # temp keyboard controls to test humanoid controller
        if gui_input.get_key(KeyNS.W):
            # walk forward in the camera yaw direction
            humancontroller_base_user_input[0] += 1
        if gui_input.get_key(KeyNS.S):
            # walk forward in the opposite to camera yaw direction
            humancontroller_base_user_input[0] -= 1

        if self._hint_walk_dir:
            humancontroller_base_user_input[0] += self._hint_walk_dir.x
            humancontroller_base_user_input[2] += self._hint_walk_dir.z

            self._recorder.record("hint_walk_dir", self._hint_walk_dir)

        else:
            self._recorder.record("cam_yaw", self._cam_yaw)
            self._recorder.record(
                "walk_forward_back", humancontroller_base_user_input[0]
            )

            rot_y_rad = -self._cam_yaw + np.pi
            rotation = mn.Quaternion.rotation(
                mn.Rad(rot_y_rad),
                mn.Vector3(0, 1, 0),
            )
            humancontroller_base_user_input = np.array(
                rotation.transform_vector(
                    mn.Vector3(humancontroller_base_user_input)
                )
            )

        self._recorder.record(
            "base_user_input", humancontroller_base_user_input
        )

        relative_pos = mn.Vector3(humancontroller_base_user_input)

        base_offset = self.get_articulated_agent().params.base_offset
        # base_offset is basically the offset from the humanoid's root (often
        # located near its pelvis) to the humanoid's feet (where it should
        # snap to the navmesh), for example (0, -0.9, 0).
        prev_query_pos = (
            self._humanoid_controller.obj_transform_base.translation
            + base_offset
        )

        self._humanoid_controller.calculate_walk_pose(relative_pos)

        # calculate_walk_pose has updated obj_transform_base.translation with
        # desired motion, but this should be filtered (restricted to navmesh).
        target_query_pos = (
            self._humanoid_controller.obj_transform_base.translation
            + base_offset
        )
        filtered_query_pos = self._env._sim.step_filter(
            prev_query_pos, target_query_pos
        )
        # fixup is the difference between the movement allowed by step_filter
        # and the requested base movement.
        fixup = filtered_query_pos - target_query_pos
        self._humanoid_controller.obj_transform_base.translation += fixup

        if gui_input.get_key(KeyNS.F):
            if self.selected_obj is not None:
                obj_pos = self.selected_obj.translation
                self._humanoid_controller.calculate_reach_pose(obj_pos)
                # final_coord = self._humanoid_controller.calculate_reach_pose_2(self.ind)
                # box_half_size = 0.03
                # box_offset = mn.Vector3(
                #     box_half_size, box_half_size, box_half_size
                # )
                # self.line_renderer.draw_box(
                #     final_coord - box_offset,
                #     final_coord + box_offset,
                #     mn.Color3(255 / 255, 128 / 255, 0)
                # )         
                # print(final_coord)
        if gui_input.get_key_up(KeyNS.F):
            self._humanoid_controller.obj_transform_offset = mn.Matrix4()
            self._humanoid_controller.calculate_stop_pose()
            self.ind += 1
        humanoidjoint_action = np.array(self._humanoid_controller.get_pose())
            
        return humanoidjoint_action
