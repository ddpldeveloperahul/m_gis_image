import sys
import numpy as np
import pandas as pd
import os

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QFileDialog

import open3d as o3d
import laspy


# =========================
# UTILS
# =========================
def meter_to_feet(m):
    return m * 3.28084

def save_csv(points, total_m, total_ft):
    os.makedirs("output", exist_ok=True)

    data = {
        "points": str(points),
        "total_distance_m": total_m,
        "total_distance_ft": total_ft
    }

    df = pd.DataFrame([data])
    file = "output/measurements.csv"

    if os.path.exists(file):
        df.to_csv(file, mode='a', header=False, index=False)
    else:
        df.to_csv(file, index=False)


# =========================
# VIEWER
# =========================
class Viewer(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("🔥 3D Distance Tool")
        self.resize(400, 320)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.label = QLabel("No file loaded")
        layout.addWidget(self.label)

        # BUTTONS
        self.btn_browse = QPushButton("📂 Browse File")
        layout.addWidget(self.btn_browse)

        self.btn_start = QPushButton("Start Measurement")
        layout.addWidget(self.btn_start)

        self.btn_back = QPushButton("⬅️ Undo Last Point")
        layout.addWidget(self.btn_back)

        self.btn_reset = QPushButton("🔄 Reset")
        layout.addWidget(self.btn_reset)

        # EVENTS
        self.btn_browse.clicked.connect(self.browse_file)
        self.btn_start.clicked.connect(self.start_measurement)
        self.btn_back.clicked.connect(self.undo_last)
        self.btn_reset.clicked.connect(self.reset_all)

        # STATE
        self.display_geometry = None
        self.pick_geometry = None
        self.selected_points = []
        self.total_distance = 0

    # =========================
    # BROWSE FILE
    # =========================
    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select 3D File",
            "",
            "3D Files (*.obj *.ply *.pcd *.las *.laz)"
        )

        if file_path:
            try:
                self.load_file(file_path)
                self.selected_points = []
                self.total_distance = 0

                self.label.setText(f"Loaded: {os.path.basename(file_path)}")
                print("✅ File Loaded:", file_path)

            except Exception as e:
                print("❌ Error:", e)

    # =========================
    # LOAD FILE (🔥 FIXED)
    # =========================
    def load_file(self, path):
        ext = path.lower()

        if ext.endswith(".obj"):
            print("📦 Loading OBJ...")

            mesh = o3d.io.read_triangle_mesh(path)

            if len(mesh.triangles) == 0:
                print("⚠️ No triangles → point cloud")

                pts = np.asarray(mesh.vertices)
                pcd = o3d.geometry.PointCloud()
                pcd.points = o3d.utility.Vector3dVector(pts)

                self.pick_geometry = pcd
                self.display_geometry = pcd

            else:
                print("✅ Mesh detected")

                mesh.compute_vertex_normals()

                # 🔥 dense point cloud for picking
                pcd = mesh.sample_points_poisson_disk(200000)

                self.pick_geometry = pcd
                self.display_geometry = mesh

        elif ext.endswith(".ply") or ext.endswith(".pcd"):
            pcd = o3d.io.read_point_cloud(path)
            self.pick_geometry = pcd
            self.display_geometry = pcd

        elif ext.endswith(".las") or ext.endswith(".laz"):
            las = laspy.read(path)
            xyz = np.vstack((las.x, las.y, las.z)).T

            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(xyz)

            self.pick_geometry = pcd
            self.display_geometry = pcd

        else:
            raise Exception("❌ Unsupported format")

    # =========================
    # SCALE
    # =========================
    def detect_scale(self, raw_dist):
        if raw_dist > 100:
            return 0.001
        elif raw_dist > 10:
            return 0.01
        return 1.0

    # =========================
    # START MEASUREMENT
    # =========================
    def start_measurement(self):

        if self.pick_geometry is None:
            print("❌ Load file first")
            return

        print("\n👉 SHIFT + Click → Select points")
        print("👉 Press Q when done\n")

        # 🔥 STEP 1: PICKING (POINT CLOUD)
        vis = o3d.visualization.VisualizerWithEditing()
        vis.create_window("Pick Points", 1200, 800)

        vis.add_geometry(self.pick_geometry)

        vis.run()
        vis.destroy_window()

        picked = vis.get_picked_points()

        if len(picked) == 0:
            return

        pts = np.asarray(self.pick_geometry.points)

        # 🔥 APPEND MODE
        for i in picked:
            self.selected_points.append(pts[i])

        self.calculate_distance()

    # =========================
    # CALCULATE
    # =========================
    def calculate_distance(self):
        total_distance = 0
        lines = []
        line_points = []

        print("\n📏 SEGMENT DISTANCES:")

        for i in range(len(self.selected_points) - 1):
            p1 = self.selected_points[i]
            p2 = self.selected_points[i + 1]

            raw = np.linalg.norm(p2 - p1)
            SCALE = self.detect_scale(raw)

            dist = raw * SCALE
            total_distance += dist

            print(f"Point{i+1} → Point{i+2} : {dist:.3f} m")

            line_points.append(p1)
            line_points.append(p2)
            lines.append([2*i, 2*i+1])

        self.total_distance = total_distance
        total_ft = meter_to_feet(total_distance)

        print("\n🔥 TOTAL DISTANCE:")
        print(f"{total_distance:.3f} meters")

        self.label.setText(f"Total: {total_distance:.2f} m | {total_ft:.2f} ft")

        save_csv(self.selected_points, total_distance, total_ft)

        # 🔥 DRAW RESULT ON MESH
        line_set = o3d.geometry.LineSet()
        line_set.points = o3d.utility.Vector3dVector(line_points)
        line_set.lines = o3d.utility.Vector2iVector(lines)
        line_set.colors = o3d.utility.Vector3dVector([[0, 1, 0] for _ in lines])

        vis = o3d.visualization.Visualizer()
        vis.create_window("3D Result", 1200, 800)

        vis.add_geometry(self.display_geometry)
        vis.add_geometry(line_set)

        opt = vis.get_render_option()
        opt.line_width = 10
        opt.background_color = np.array([1, 1, 1])
        opt.light_on = True

        vis.run()
        vis.destroy_window()

    # =========================
    # RESET
    # =========================
    def reset_all(self):
        print("\n🔄 Reset")
        self.selected_points = []
        self.total_distance = 0
        self.label.setText("Total Distance: 0 m | 0 ft")

    # =========================
    # UNDO
    # =========================
    def undo_last(self):
        if len(self.selected_points) > 1:
            print("⬅️ Undo")
            self.selected_points.pop()
            self.calculate_distance()
        else:
            print("❌ Nothing to undo")


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    app = QApplication(sys.argv)

    viewer = Viewer()
    viewer.show()

    sys.exit(app.exec_())