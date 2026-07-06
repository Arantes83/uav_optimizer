import importlib
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


fake_bpy = types.SimpleNamespace()
sys.modules["bpy"] = fake_bpy
sys.modules["bpy.types"] = types.SimpleNamespace(Operator=object)
sys.modules["bmesh"] = types.SimpleNamespace()
sys.modules["mathutils"] = types.SimpleNamespace()

op_quadriflow = importlib.import_module("op_quadriflow")


def make_props(**overrides):
    base = {
        "quadriflow_target_mode": "QUAD_COUNT",
        "target_quad_count": 50000,
        "quadriflow_target_ratio": 1.0,
        "quadriflow_target_density": 4.0,
        "quadriflow_density_unit": "M2",
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


class QuadriFlowTargetingTests(unittest.TestCase):
    def test_diagnostic_summary_reports_non_manifold_mesh(self):
        report = types.SimpleNamespace(
            face_count=100,
            degenerate_faces=0,
            loose_edges=0,
            loose_vertices=0,
            non_manifold_edges=12,
            boundary_edges=0,
        )

        message = op_quadriflow._quadriflow_diagnostic_summary(report)

        self.assertIn("non-manifold edges detected", message.lower())

    def test_diagnostic_summary_reports_open_surface(self):
        report = types.SimpleNamespace(
            face_count=100,
            degenerate_faces=0,
            loose_edges=0,
            loose_vertices=0,
            non_manifold_edges=0,
            boundary_edges=8,
        )

        message = op_quadriflow._quadriflow_diagnostic_summary(report)

        self.assertIn("open boundary edges detected", message.lower())

    def test_diagnostic_summary_empty_for_closed_two_manifold_mesh(self):
        report = types.SimpleNamespace(
            face_count=100,
            degenerate_faces=0,
            loose_edges=0,
            loose_vertices=0,
            non_manifold_edges=0,
            boundary_edges=0,
        )

        self.assertEqual(op_quadriflow._quadriflow_diagnostic_summary(report), "")

    def test_failure_message_appends_diagnostic_summary(self):
        report = types.SimpleNamespace(
            face_count=100,
            degenerate_faces=0,
            loose_edges=0,
            loose_vertices=0,
            non_manifold_edges=12,
            boundary_edges=8,
        )

        message = op_quadriflow._quadriflow_failure_message(
            "forced quadriflow failure",
            report,
        )

        self.assertIn("forced quadriflow failure", message)
        self.assertIn("non-manifold edges detected", message.lower())
        self.assertIn("open boundary edges detected", message.lower())

    def test_quad_count_mode_uses_explicit_target(self):
        props = make_props(target_quad_count=1234)

        target = op_quadriflow._resolve_target_faces(
            props,
            current_vertices=2000,
            current_tris=4000,
            total_area_m2=25.0,
        )

        self.assertEqual(target, 1234)

    def test_ratio_mode_converts_triangle_equivalent_to_quad_target(self):
        props = make_props(quadriflow_target_mode="RATIO", quadriflow_target_ratio=0.25)

        target = op_quadriflow._resolve_target_faces(
            props,
            current_vertices=8000,
            current_tris=10000,
            total_area_m2=25.0,
        )

        self.assertEqual(target, 1250)

    def test_density_mode_uses_surface_area(self):
        props = make_props(
            quadriflow_target_mode="DENSITY",
            quadriflow_target_density=8.0,
            quadriflow_density_unit="M2",
        )

        target = op_quadriflow._resolve_target_faces(
            props,
            current_vertices=8000,
            current_tris=10000,
            total_area_m2=50.0,
        )

        self.assertEqual(target, 200)

    def test_noop_detection_flags_identical_topology(self):
        self.assertTrue(
            op_quadriflow._quadriflow_result_looks_unchanged(
                before_vertices=1200,
                before_faces=900,
                after_vertices=1200,
                after_faces=900,
            )
        )

    def test_noop_detection_accepts_changed_topology(self):
        self.assertFalse(
            op_quadriflow._quadriflow_result_looks_unchanged(
                before_vertices=1200,
                before_faces=900,
                after_vertices=1800,
                after_faces=1600,
            )
        )


if __name__ == "__main__":
    unittest.main()
