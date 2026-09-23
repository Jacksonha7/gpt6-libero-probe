"""相机几何：世界坐标 <-> 像素。

约定（test_geom.py 里验证过）：
  * robosuite 原始 obs 图像是 OpenGL 约定（上下颠倒）。`upright(img) = img[::-1]` 才是正着的、
    没有左右镜像的图，这也是发给 GPT 的图。openpi 喂 VLA 的 `[::-1, ::-1]` 是它的左右镜像，别混用。
  * 像素坐标一律用 (u, v) = (列, 行)，原点在 upright 图的左上角。
  * robosuite 1.4 的 transform_from_pixels_to_world 对 [H,W,1] 深度图取形状有 bug，这里自己写反投影。
"""
import numpy as np


def upright(img):
    return np.ascontiguousarray(img[::-1])


class Camera:
    def __init__(self, sim, name, height, width):
        self.sim, self.name, self.h, self.w = sim, name, height, width

    def world_to_pix_mat(self):
        """4x4：世界系齐次点 -> [u*z, v*z, z, 1]。与 robosuite.utils.camera_utils 同公式
        （那个模块 import h5py，客户端 venv 里没装，所以这里自己写）。"""
        sim, cid = self.sim, self.sim.model.camera_name2id(self.name)
        f = 0.5 * self.h / np.tan(sim.model.cam_fovy[cid] * np.pi / 360)
        K = np.array([[f, 0, self.w / 2, 0], [0, f, self.h / 2, 0], [0, 0, 1, 0], [0, 0, 0, 1.0]])
        R = np.eye(4)
        R[:3, :3] = sim.data.cam_xmat[cid].reshape(3, 3)
        R[:3, 3] = sim.data.cam_xpos[cid]
        R = R @ np.diag([1.0, -1.0, -1.0, 1.0])      # MuJoCo 相机轴 -> 常规相机轴
        return K @ np.linalg.inv(R)

    def project(self, p_world):
        """世界系 3D 点 -> upright 图上的 (u, v) 浮点像素，以及相机系深度。"""
        p = self.world_to_pix_mat() @ np.append(np.asarray(p_world, dtype=float), 1.0)
        return np.array([p[0] / p[2], p[1] / p[2]]), p[2]

    def depth_map(self, raw_depth_obs):
        """obs['<cam>_depth']（归一化、上下颠倒）-> upright 的米制深度 [H, W]。"""
        ext = self.sim.model.stat.extent
        near, far = self.sim.model.vis.map.znear * ext, self.sim.model.vis.map.zfar * ext
        d = near / (1.0 - raw_depth_obs * (1.0 - near / far))
        return upright(d)[..., 0]

    def backproject(self, u, v, depth_m):
        """upright 图上的 (u, v) + 米制深度图 -> 世界系 3D 点。深度取 3x3 邻域中位数抗边缘噪声。"""
        ui = int(np.clip(round(u), 0, self.w - 1))
        vi = int(np.clip(round(v), 0, self.h - 1))
        patch = depth_m[max(vi - 1, 0):vi + 2, max(ui - 1, 0):ui + 2]
        z = float(np.median(patch))
        p = np.linalg.inv(self.world_to_pix_mat()) @ np.array([u * z, v * z, z, 1.0])
        return p[:3]
