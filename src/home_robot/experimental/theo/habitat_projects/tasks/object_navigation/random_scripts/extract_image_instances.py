"""
This script is intended to run from the "src" root:
python home_robot/experimental/theo/habitat_projects/tasks/object_navigation/random_scripts/extract_image_instances.py
"""
from pathlib import Path
import sys

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent.parent.parent.parent.parent.parent.parent
    ),
)

from habitat.core.env import Env

from home_robot.experimental.theo.habitat_projects.utils.config_utils import get_config


if __name__ == "__main__":
    config_path = (
        Path(__file__).resolve().parent.parent / "configs/task/hm3d_imageinstancegoal_val.yaml"
    )
    config, config_str = get_config(config_path)
    print(config)
    env = Env(config=config.TASK_CONFIG)
    obs = env.reset()
    print(obs["instance_imagegoal"])
