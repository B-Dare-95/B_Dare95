# Author: Ahmed Helmy Abdelmagid
# Description: Creates wall dimensions on all levels or selected level
# Fixed: dimensioned_face string/object mismatch, added null guards for Revit 2026

from pyrevit import DB, forms
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.DB import UV

uiapp = __revit__
app = uiapp.Application
doc = uiapp.ActiveUIDocument.Document

ALL_LEVELS = "All Levels"
SELECT_LEVEL = "Select Level"
OFFSET_MULTIPLIER_INCREMENT = 10
TOLERANCE = doc.Application.ShortCurveTolerance


class UIHandler:
    @staticmethod
    def get_user_input():
        level_options = [ALL_LEVELS, SELECT_LEVEL]
        selected_option = forms.ask_for_one_item(
            level_options, default=ALL_LEVELS, title="Dimension Options"
        )

        selected_level = (
            UIHandler.get_selected_level()
            if selected_option == SELECT_LEVEL
            else None
        )

        selected_face = forms.ask_for_one_item(
            ["Internal", "External"], default="External", title="Dimension Face"
        )
        offset_distance = UIHandler.get_offset_distance()

        if offset_distance is not None:
            offset_distance = DB.UnitUtils.ConvertToInternalUnits(
                offset_distance, DB.UnitTypeId.Millimeters
            )

        return selected_option, selected_level, selected_face, offset_distance

    @staticmethod
    def get_selected_level():
        level_elements = (
            DB.FilteredElementCollector(doc)
            .OfCategory(DB.BuiltInCategory.OST_Levels)
            .WhereElementIsNotElementType()
            .ToElements()
        )
        level_dict = {level.Name: level for level in level_elements}
        selected_level_name = forms.SelectFromList.show(
            sorted(level_dict.keys()), title="Select Level"
        )
        return level_dict.get(selected_level_name)

    @staticmethod
    def get_offset_distance():
        offset_distance_str = forms.ask_for_string(
            default="1000",
            prompt="Enter the offset distance (in millimeters):",
            title="Offset Distance",
        )

        if offset_distance_str:
            try:
                offset_distance = float(offset_distance_str)
                if offset_distance <= 0:
                    TaskDialog.Show("Error", "Offset distance must be a positive number.")
                    return None
                return offset_distance
            except ValueError:
                TaskDialog.Show("Error", "Invalid input. Please enter a valid number.")
                return None
        else:
            return None

    @staticmethod
    def get_dimensioning_type():
        dimensioning_options = ["Wall Thickness", "Overall"]
        return forms.ask_for_one_item(
            dimensioning_options,
            default="Wall Thickness",
            title="Dimensioning Type",
        )


class GeometryHandler:
    wall_vector_cache = {}

    @staticmethod
    def get_wall_vectors(wall):
        # .Value replaces .IntegerValue in Revit 2026 (ElementId is now 64-bit)
        wall_id = wall.Id.Value
        if wall_id in GeometryHandler.wall_vector_cache:
            return GeometryHandler.wall_vector_cache[wall_id]

        loc_curve = wall.Location
        if not isinstance(loc_curve, DB.LocationCurve):
            return None, None

        loc_line = loc_curve.Curve
        wall_dir = loc_line.Direction.Normalize()
        perp_dir = wall_dir.CrossProduct(DB.XYZ.BasisZ)

        GeometryHandler.wall_vector_cache[wall_id] = (wall_dir, perp_dir)
        return wall_dir, perp_dir

    @staticmethod
    def get_wall_solid(wall, options=None):
        options = options or DB.Options()

        for geometry_object in wall.get_Geometry(options):
            if isinstance(geometry_object, DB.Solid) and geometry_object.Faces.Size > 0:
                return geometry_object

        return None

    @staticmethod
    def get_wall_outer_edges(wall, opts, dimension_face):
        """
        dimension_face must be the STRING "External" or "Internal".
        Previously this was accidentally passed a Face object in some call sites,
        which caused silent logic errors.
        """
        try:
            wall_solid = GeometryHandler.get_wall_solid(wall, opts)
            if not wall_solid:
                return []

            edges = []
            for face in wall_solid.Faces:
                for edge_loop in face.EdgeLoops:
                    for edge in edge_loop:
                        try:
                            edge_c = edge.AsCurve()
                            if isinstance(edge_c, DB.Line):
                                if edge_c.Direction.IsAlmostEqualTo(
                                    DB.XYZ.BasisZ
                                ) or edge_c.Direction.IsAlmostEqualTo(
                                    -DB.XYZ.BasisZ
                                ):
                                    edges.append(edge)
                        except Exception as e:
                            print("Error processing edge for wall {}: {}".format(wall.Id, e))
                            continue

            if dimension_face == "External":
                edge_endpoints = {}
                outermost_edges = []
                for edge in edges:
                    edge_c = edge.AsCurve()
                    start_point = edge_c.GetEndPoint(0)
                    end_point = edge_c.GetEndPoint(1)
                    if (
                        (start_point, end_point) not in edge_endpoints
                        and (end_point, start_point) not in edge_endpoints
                    ):
                        outermost_edges.append(edge)
                        edge_endpoints[(start_point, end_point)] = True
                return outermost_edges
            else:
                return edges

        except Exception as e:
            print("Error processing wall {}: {}".format(wall.Id, e))
            return []

    @staticmethod
    def get_reference_position(edge, wall, dimension_line):
        edge_curve = edge.AsCurve()
        edge_midpoint = edge_curve.Evaluate(0.5, True)
        wall_location = wall.Location.Curve
        intersection_result = dimension_line.Project(edge_midpoint)
        projected_point = intersection_result.XYZPoint
        position = wall_location.Project(projected_point).Parameter
        return position

    @staticmethod
    def get_wall_end_references(wall, options):
        wall_end_references = []
        wall_solid = GeometryHandler.get_wall_solid(wall, options)

        if wall_solid is not None:
            end_faces = GeometryHandler.find_end_faces(wall_solid)
            for face in end_faces:
                wall_end_references.append(face.Reference)

        return wall_end_references

    @staticmethod
    def find_end_faces(solid):
        end_faces = []
        longest_span = None
        max_length = 0

        for edge in solid.Edges:
            edge_curve = edge.AsCurve()
            if edge_curve.Length > max_length:
                longest_span = edge_curve
                max_length = edge_curve.Length

        if longest_span:
            longest_direction = (
                longest_span.GetEndPoint(1) - longest_span.GetEndPoint(0)
            ).Normalize()
            for face in solid.Faces:
                normal = face.ComputeNormal(UV(0.5, 0.5))
                cross = normal.CrossProduct(longest_direction)
                # Use a small tolerance instead of exact zero comparison
                if cross.GetLength() < TOLERANCE:
                    end_faces.append(face)

        return end_faces


class RevitTransactionManager:
    @staticmethod
    def create_wall_dimensions(
        doc,
        selected_option,
        selected_level,
        selected_face,
        offset_distance,
        tolerance,
        selected_dimensioning_type,
    ):
        level_elements = (
            DB.FilteredElementCollector(doc)
            .OfCategory(DB.BuiltInCategory.OST_Levels)
            .WhereElementIsNotElementType()
            .ToElements()
        )
        existing_dim_endpoints = set()

        for level in level_elements:
            if selected_option == SELECT_LEVEL and level.Id != selected_level.Id:
                continue

            view = RevitAPIUtils.get_floor_plan_view_for_level(doc, level)
            if view is None:
                continue

            walls_on_level = list(RevitGeometryUtils.collect_walls(doc, view.Id, level.Id))

            if not walls_on_level:
                continue

            geometry_options = DB.Options()
            geometry_options.ComputeReferences = True
            geometry_options.IncludeNonVisibleObjects = True
            geometry_options.View = view

            for wall in walls_on_level:
                try:
                    wall_dir, perp_dir = GeometryHandler.get_wall_vectors(wall)

                    # Guard: skip walls with no valid location curve
                    if wall_dir is None or perp_dir is None:
                        continue

                    existing_line = wall.Location.Curve

                    side_faces_ext = list(
                        DB.HostObjectUtils.GetSideFaces(wall, DB.ShellLayerType.Exterior)
                    )
                    side_faces_int = list(
                        DB.HostObjectUtils.GetSideFaces(wall, DB.ShellLayerType.Interior)
                    )

                    # Guard: skip if side faces are unavailable (e.g. curtain walls)
                    if not side_faces_ext or not side_faces_int:
                        continue

                    wall_ext_face_ref = side_faces_ext[0]
                    wall_int_face_ref = side_faces_int[0]

                    wall_ext_face = wall.GetGeometryObjectFromReference(wall_ext_face_ref)
                    wall_int_face = wall.GetGeometryObjectFromReference(wall_int_face_ref)

                    # Guard: ensure face geometry resolved correctly
                    if wall_ext_face is None or wall_int_face is None:
                        continue

                    offset_dir = (
                        -perp_dir if selected_face == "External" else perp_dir
                    )

                    original_off_crv = existing_line.CreateTransformed(
                        DB.Transform.CreateTranslation(
                            offset_dir.Multiply(offset_distance)
                        )
                    )
                    off_crv = original_off_crv

                    vert_edge_sub = DB.ReferenceArray()

                    if selected_dimensioning_type == "Wall Thickness":
                        # FIX: pass selected_face (string), NOT dimensioned_face (Face object)
                        # Previously `dimensioned_face` was passed here, which is a Face object
                        # and would never equal the string "External", breaking the edge filter.
                        vert_edges = GeometryHandler.get_wall_outer_edges(
                            wall, geometry_options, selected_face
                        )

                        intersecting_walls = set(
                            RevitAPIUtils.find_intersecting_walls(doc, wall)
                        )
                        vert_edges.extend(
                            edge
                            for int_wall in intersecting_walls
                            for edge in GeometryHandler.get_wall_outer_edges(
                                int_wall, geometry_options, selected_face
                            )
                        )

                        vert_edges.sort(
                            key=lambda e: e.AsCurve()
                            .GetEndPoint(0)
                            .DistanceTo(existing_line.GetEndPoint(0))
                        )
                        reference_positions = set()

                        for edge in vert_edges:
                            value = round(
                                DB.UnitUtils.ConvertFromInternalUnits(
                                    edge.ApproximateLength, DB.UnitTypeId.Millimeters
                                ),
                                2,
                            )
                            if value > tolerance:
                                ref_position = GeometryHandler.get_reference_position(
                                    edge, wall, off_crv
                                )
                                if not any(
                                    abs(ref_position - existing_pos) < tolerance
                                    for existing_pos in reference_positions
                                ):
                                    vert_edge_sub.Append(edge.Reference)
                                    reference_positions.add(ref_position)

                    else:  # "Overall"
                        wall_end_references = GeometryHandler.get_wall_end_references(
                            wall, geometry_options
                        )
                        for ref in wall_end_references:
                            vert_edge_sub.Append(ref)

                    if vert_edge_sub.Size >= 2:
                        line = off_crv
                        offset_multiplier = 1
                        while not RevitAPIUtils.is_space_free_for_dimension(
                            doc, line, view
                        ):
                            offset_multiplier += 1
                            line = RevitAPIUtils.offset_dimension_line(
                                original_off_crv,
                                OFFSET_MULTIPLIER_INCREMENT * offset_multiplier,
                            )

                        dim_line = DB.Line.CreateBound(
                            line.GetEndPoint(0), line.GetEndPoint(1)
                        )
                        dim_tuple = tuple(
                            sorted((dim_line.GetEndPoint(0), dim_line.GetEndPoint(1)))
                        )
                        if dim_tuple not in existing_dim_endpoints:
                            doc.Create.NewDimension(view, dim_line, vert_edge_sub)
                            existing_dim_endpoints.add(dim_tuple)

                except Exception as e:
                    print("Failed to create dimension for wall {}: {}".format(wall.Id, e))
                    continue


class RevitGeometryUtils:
    @staticmethod
    def collect_walls(doc, view_id, level_id):
        return (
            DB.FilteredElementCollector(doc, view_id)
            .OfCategory(DB.BuiltInCategory.OST_Walls)
            .WherePasses(DB.ElementLevelFilter(level_id))
            .WhereElementIsNotElementType()
            .ToElements()
        )


class RevitAPIUtils:
    @staticmethod
    def get_floor_plan_view_for_level(doc, level):
        view_collector = (
            DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan).ToElements()
        )
        return next(
            (
                view
                for view in view_collector
                if view.GenLevel is not None
                and view.GenLevel.Name == level.Name
                and not view.IsTemplate
            ),
            None,
        )

    @staticmethod
    def find_intersecting_walls(doc, wall):
        bbox = wall.get_BoundingBox(None)
        if bbox is None:
            return set()
        outline = DB.Outline(bbox.Min, bbox.Max)
        return {
            w
            for w in DB.FilteredElementCollector(doc)
            .OfClass(DB.Wall)
            .WherePasses(DB.BoundingBoxIntersectsFilter(outline))
            .WhereElementIsNotElementType()
            .ToElements()
            if w.Id != wall.Id
        }

    @staticmethod
    def is_space_free_for_dimension(doc, line, view):
        start_pt = line.GetEndPoint(0)
        end_pt = line.GetEndPoint(1)

        min_point = DB.XYZ(min(start_pt.X, end_pt.X), start_pt.Y - 0.5, 0)
        max_point = DB.XYZ(max(start_pt.X, end_pt.X), start_pt.Y + 0.5, 0)

        outline = DB.Outline(min_point, max_point)

        intersecting_dimensions = (
            DB.FilteredElementCollector(doc, view.Id)
            .OfCategory(DB.BuiltInCategory.OST_Dimensions)
            .WherePasses(DB.BoundingBoxIntersectsFilter(outline))
            .WhereElementIsNotElementType()
            .ToElements()
        )

        return len(intersecting_dimensions) == 0

    @staticmethod
    def offset_dimension_line(line, offset_value):
        transform = DB.Transform.CreateTranslation(DB.XYZ(0, offset_value, 0))
        return line.CreateTransformed(transform)


def main():
    try:
        selected_option, selected_level, selected_face, offset_distance = (
            UIHandler.get_user_input()
        )
        selected_dimensioning_type = UIHandler.get_dimensioning_type()

        if offset_distance is None:
            TaskDialog.Show("Warning", "Operation cancelled by the user.")
        else:
            with DB.Transaction(doc, "Auto Dimension Walls") as transaction:
                try:
                    transaction.Start()
                    RevitTransactionManager.create_wall_dimensions(
                        doc,
                        selected_option,
                        selected_level,
                        selected_face,
                        offset_distance,
                        TOLERANCE,
                        selected_dimensioning_type,
                    )
                    transaction.Commit()
                except Exception as e:
                    transaction.RollBack()
                    TaskDialog.Show(
                        "Error",
                        "An error occurred while dimensioning walls:\n{}".format(str(e)),
                    )
                    raise
    except Exception as e:
        TaskDialog.Show("Error", "An unexpected error occurred:\n{}".format(str(e)))
        raise


if __name__ == "__main__":
    main()