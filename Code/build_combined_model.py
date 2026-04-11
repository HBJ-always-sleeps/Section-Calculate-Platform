# -*- coding: utf-8 -*-
"""
Combined Model Builder - V4 DMX/Overbreak + V2 Geological Logic
Uses correct coordinate transformation from V4
"""

import json
import math
import numpy as np
from typing import Dict, List, Tuple, Optional
from pathlib import Path

# Layer categories definition
LAYER_CATEGORIES = {
    'silt_fill': {'name_cn': '淤泥与填土', 'color': '#7f8c8d'},
    'clay': {'name_cn': '黏土', 'color': '#A52A2A'},
    'sand_gravel': {'name_cn': '砂与碎石类', 'color': '#f1c40f'}
}


def categorize_layer(layer_name: str) -> Optional[str]:
    """Categorize layer name into one of three categories"""
    if not layer_name:
        return None
    layer_lower = layer_name.lower()
    if any(k in layer_lower for k in ['淤泥', '填土', 'silt', 'fill']):
        return 'silt_fill'
    elif any(k in layer_lower for k in ['黏土', 'clay']):
        return 'clay'
    elif any(k in layer_lower for k in ['砂', '碎石', 'sand', 'gravel']):
        return 'sand_gravel'
    return None


def load_json(json_path: str) -> Dict:
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def transform_to_spine_aligned(cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle):
    """
    Coordinate transformation: CAD local coords -> Engineering coords
    This is the CORRECT version from V4
    
    cad_x, cad_y: CAD coordinates (Y is elevation in CAD)
    ref_x, ref_y: Reference point (L1 intersection)
    spine_x, spine_y: Spine point (engineering coordinates)
    rotation_angle: Rotation angle to align with spine
    
    Returns: (eng_x, eng_y, z) where:
      - eng_x: engineering X (horizontal position)
      - eng_y: engineering Y (mileage along spine)
      - z: elevation
    """
    # Z is elevation difference from reference
    z = cad_y - ref_y
    
    # X offset from reference
    dx = cad_x - ref_x
    
    # Rotate to align with spine direction
    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)
    
    rotated_dx = dx * cos_a
    rotated_dy = dx * sin_a
    
    # Engineering coordinates
    eng_x = spine_x + rotated_dx
    eng_y = spine_y + rotated_dy
    
    return eng_x, eng_y, z


# ==================== V4 Core Algorithms: Feature Point Alignment ====================

def find_bottom_corners(points: np.ndarray, z_tolerance: float = 0.3) -> Tuple[int, int]:
    """
    Find bottom corner indices in trench polyline
    V4 algorithm: detect corners by Z value and slope change
    """
    n = len(points)
    if n < 5:
        return 0, n - 1
    
    z_values = points[:, 2]
    z_min = np.min(z_values)
    z_max = np.max(z_values)
    
    # Find bottom segment (Z close to minimum)
    bottom_mask = z_values <= (z_min + z_tolerance)
    bottom_indices = np.where(bottom_mask)[0]
    
    if len(bottom_indices) < 2:
        return 0, n - 1
    
    # Find left and right corners (transition points)
    left_corner = bottom_indices[0]
    right_corner = bottom_indices[-1]
    
    # Verify by slope change
    for i in range(1, min(10, n)):
        if not bottom_mask[i] and bottom_mask[i-1]:
            left_corner = i - 1
            break
    
    for i in range(n - 2, max(n - 10, 0), -1):
        if not bottom_mask[i] and bottom_mask[i+1]:
            right_corner = i + 1
            break
    
    return left_corner, right_corner


def resample_trench_segmented(points: np.ndarray, 
                               left_samples: int = 15,
                               bottom_samples: int = 30,
                               right_samples: int = 15) -> np.ndarray:
    """
    V4 segmented resampling: left slope / bottom / right slope
    Ensures corner points align longitudinally
    """
    n = len(points)
    if n < 5:
        return points
    
    # Find corners
    left_corner, right_corner = find_bottom_corners(points)
    
    # Extract segments
    left_slope = points[:left_corner + 1]
    bottom = points[left_corner:right_corner + 1]
    right_slope = points[right_corner:]
    
    # Resample each segment
    resampled_left = resample_line_uniform(left_slope, left_samples) if len(left_slope) > 1 else left_slope
    resampled_bottom = resample_line_uniform(bottom, bottom_samples) if len(bottom) > 1 else bottom
    resampled_right = resample_line_uniform(right_slope, right_samples) if len(right_slope) > 1 else right_slope
    
    # Combine (avoid duplicate corners)
    result = np.vstack([resampled_left[:-1], resampled_bottom[:-1], resampled_right])
    
    return result


def resample_line_uniform(points: np.ndarray, num_samples: int) -> np.ndarray:
    """Uniform resampling of a line"""
    if len(points) < 2:
        return points
    
    # Calculate cumulative distances
    diffs = np.diff(points, axis=0)
    distances = np.sqrt(np.sum(diffs**2, axis=1))
    cumulative = np.concatenate([[0], np.cumsum(distances)])
    total_length = cumulative[-1]
    
    if total_length < 1e-6:
        return points
    
    # Sample at uniform intervals
    sample_distances = np.linspace(0, total_length, num_samples)
    
    # Interpolate
    result = np.zeros((num_samples, 3))
    for i in range(3):
        result[:, i] = np.interp(sample_distances, cumulative, points[:, i])
    
    return result


def resample_polygon_equidistant(points: np.ndarray, n_samples: int = 64) -> np.ndarray:
    """
    V2 geological polygon resampling: equidistant sampling
    """
    if len(points) < 3:
        return points
    
    # Ensure closed polygon
    if not np.allclose(points[0], points[-1]):
        points = np.vstack([points, points[0]])
    
    n = len(points)
    
    # Calculate cumulative perimeter distances
    diffs = np.diff(points, axis=0)
    segment_lengths = np.sqrt(np.sum(diffs**2, axis=1))
    cumulative = np.concatenate([[0], np.cumsum(segment_lengths)])
    total_perimeter = cumulative[-1]
    
    if total_perimeter < 1e-6:
        return points[:n_samples]
    
    # Sample at equidistant intervals
    sample_distances = np.linspace(0, total_perimeter, n_samples, endpoint=False)
    
    # Interpolate
    result = np.zeros((n_samples, 3))
    for i in range(3):
        result[:, i] = np.interp(sample_distances, cumulative, points[:, i])
    
    return result


def normalize_polygon_orientation(points: np.ndarray) -> np.ndarray:
    """Ensure polygon vertices are in consistent orientation (CCW)"""
    if len(points) < 3:
        return points
    
    # Calculate signed area
    n = len(points)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i, 0] * points[j, 1]
        area -= points[j, 0] * points[i, 1]
    
    # Reverse if CW (negative area)
    if area < 0:
        return np.flip(points, axis=0)
    
    return points


def calculate_polygon_area(points: np.ndarray) -> float:
    """Calculate 2D polygon area (projected to XZ plane)"""
    if len(points) < 3:
        return 0.0
    
    n = len(points)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i, 0] * points[i, 2]
        area -= points[j, 0] * points[j, 2]
    
    return abs(area) / 2.0


def calculate_centroid(points: np.ndarray) -> Tuple[float, float]:
    """Calculate centroid X and Z coordinates"""
    if len(points) < 1:
        return 0.0, 0.0
    
    cx = np.mean(points[:, 0])
    cz = np.mean(points[:, 2])
    
    return cx, cz


def match_geological_polygons_with_similarity(
    polys_a: List[Dict],
    polys_b: List[Dict],
    distance_threshold: float = 50.0,
    area_change_threshold: float = 0.5
) -> List[Tuple[Dict, Dict]]:
    """
    V2 geological polygon matching: centroid distance + area similarity
    Uses X-coordinate only for distance (Y is mileage, varies between sections)
    """
    connections = []
    
    for p_a in polys_a:
        category_a = p_a.get('category')
        if category_a is None:
            continue
        
        centroid_a = p_a['centroid']
        area_a = p_a['area']
        
        best_match = None
        best_score = float('inf')
        
        for p_b in polys_b:
            # Must match by category
            category_b = p_b.get('category')
            if category_b != category_a:
                continue
            
            centroid_b = p_b['centroid']
            area_b = p_b['area']
            
            # X-coordinate distance only (Y is mileage)
            x_distance = abs(centroid_a[0] - centroid_b[0])
            
            if x_distance > distance_threshold:
                continue
            
            # Area similarity
            area_ratio = min(area_a, area_b) / max(area_a, area_b) if max(area_a, area_b) > 0 else 0
            
            if area_ratio < area_change_threshold:
                continue
            
            # Score: distance + area difference
            score = x_distance + (1 - area_ratio) * 100
            
            if score < best_score:
                best_score = score
                best_match = p_b
        
        if best_match is not None:
            connections.append((p_a, best_match))
    
    return connections


# ==================== Mesh Generation ====================

def generate_trench_ribbon(section_data_list: List[Dict], 
                           num_samples: int = 60) -> Dict:
    """
    Generate trench ribbon mesh using V4 segmented alignment
    """
    if len(section_data_list) < 2:
        return {'valid': False, 'vertices': [], 'faces': []}
    
    vertices = []
    faces = []
    
    for i, section in enumerate(section_data_list):
        trench_points = section.get('trench_3d')
        if trench_points is None or len(trench_points) < 5:
            continue
        
        # V4: Segmented resampling
        resampled = resample_trench_segmented(trench_points, 15, 30, 15)
        
        for pt in resampled:
            vertices.append([pt[0], section['spine_y'], pt[2]])
    
    n_sections = len(vertices) // 60 if len(vertices) > 0 else 0
    
    for i in range(n_sections - 1):
        base_a = i * 60
        base_b = (i + 1) * 60
        
        for j in range(59):
            # Triangle 1
            faces.append([base_a + j, base_b + j, base_a + j + 1])
            # Triangle 2
            faces.append([base_a + j + 1, base_b + j, base_b + j + 1])
    
    return {
        'valid': len(vertices) > 0,
        'vertices': np.array(vertices) if vertices else np.array([]),
        'faces': faces
    }


def generate_volume_mesh(poly_a: np.ndarray, poly_b: np.ndarray,
                         n_samples: int = 64) -> Tuple[List, List]:
    """
    Generate volume mesh between two polygons
    """
    # Resample both polygons
    resampled_a = resample_polygon_equidistant(poly_a, n_samples)
    resampled_b = resample_polygon_equidistant(poly_b, n_samples)
    
    vertices = []
    faces = []
    
    # Add vertices from polygon A
    for pt in resampled_a:
        vertices.append(list(pt))
    
    # Add vertices from polygon B
    for pt in resampled_b:
        vertices.append(list(pt))
    
    # Generate faces (triangles between A and B)
    for i in range(n_samples):
        next_i = (i + 1) % n_samples
        
        # Triangle 1: A[i], B[i], A[next_i]
        faces.append([i, n_samples + i, next_i])
        
        # Triangle 2: A[next_i], B[i], B[next_i]
        faces.append([next_i, n_samples + i, n_samples + next_i])
    
    return vertices, faces


def generate_taper_volume(poly: np.ndarray, centroid: Tuple[float, float],
                         n_samples: int = 64) -> Tuple[List, List]:
    """
    Generate taper volume for disappearing geological layer
    """
    resampled = resample_polygon_equidistant(poly, n_samples)
    
    vertices = []
    faces = []
    
    # Add polygon vertices
    for pt in resampled:
        vertices.append(list(pt))
    
    # Add centroid as apex
    apex = [centroid[0], np.mean(poly[:, 1]), centroid[1]]
    vertices.append(apex)
    apex_idx = n_samples
    
    # Generate faces (triangles from polygon to apex)
    for i in range(n_samples):
        next_i = (i + 1) % n_samples
        faces.append([i, next_i, apex_idx])
    
    return vertices, faces


# ==================== Main Builder Class ====================

class CombinedModelBuilder:
    """
    Combined Model Builder
    - DMX/Overbreak: V4 segmented alignment logic
    - Geological layers: V2 centroid distance + area similarity matching
    - Layer manager: V4 legend panel + toggle buttons
    """
    
    def __init__(self, section_json_path: str, spine_json_path: str,
                 num_samples_dmx: int = 60,
                 num_samples_geo: int = 64,
                 distance_threshold: float = 50.0,
                 area_ratio_threshold: float = 0.5):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.num_samples_dmx = num_samples_dmx
        self.num_samples_geo = num_samples_geo
        self.distance_threshold = distance_threshold
        self.area_ratio_threshold = area_ratio_threshold
        
        self.sections = []
        self.spine_matches = {}
        
        # Interpolation bounds for missing spine data
        self.spine_x_min = 0
        self.spine_x_max = 0
        self.spine_y_min = 0
        self.spine_y_max = 0
    
    def load_data(self) -> bool:
        """Load section and spine data"""
        try:
            section_data = load_json(self.section_json_path)
            self.sections = section_data.get('sections', [])
            print(f"Loaded {len(self.sections)} sections")
        except Exception as e:
            print(f"Error loading sections: {e}")
            return False
        
        try:
            spine_data = load_json(self.spine_json_path)
            
            # Handle both formats: matches array or direct station_value keys
            if 'matches' in spine_data:
                # Convert matches array to dict keyed by station_value
                matches_list = spine_data.get('matches', [])
                self.spine_matches = {}
                for m in matches_list:
                    station_key = str(int(m.get('station_value', 0)))
                    self.spine_matches[station_key] = m
                
                # Calculate interpolation bounds from matches
                if matches_list:
                    sorted_matches = sorted(matches_list, key=lambda m: m.get('station_value', 0))
                    self.spine_x_min = sorted_matches[0].get('spine_x', 0)
                    self.spine_x_max = sorted_matches[-1].get('spine_x', 0)
                    self.spine_y_min = sorted_matches[0].get('spine_y', 0)
                    self.spine_y_max = sorted_matches[-1].get('spine_y', 0)
                    self.station_min = sorted_matches[0].get('station_value', 0)
                    self.station_max = sorted_matches[-1].get('station_value', 0)
                    print(f"Spine bounds: X[{self.spine_x_min:.0f}, {self.spine_x_max:.0f}], Y[{self.spine_y_min:.0f}, {self.spine_y_max:.0f}]")
                    print(f"Station range: {self.station_min} -> {self.station_max}")
            else:
                # Direct key format
                self.spine_matches = spine_data
            
            print(f"Loaded {len(self.spine_matches)} spine matches")
        except Exception as e:
            print(f"Error loading spine matches: {e}")
            return False
        
        return len(self.sections) > 0 and len(self.spine_matches) > 0
    
    def _get_interpolated_spine_match(self, station_value: float) -> Dict:
        """Get spine match with interpolation for missing stations"""
        station_key = str(int(station_value))
        
        # Direct lookup
        if station_key in self.spine_matches:
            match = self.spine_matches[station_key]
            return {
                'spine_x': match.get('spine_x', 0),
                'spine_y': match.get('spine_y', 0),
                'rotation_angle': match.get('tangent_angle', 0)
            }
        
        # Interpolate between nearest stations
        if not hasattr(self, 'station_min') or not hasattr(self, 'station_max'):
            return {'spine_x': 0, 'spine_y': station_value, 'rotation_angle': 0}
        
        # Linear interpolation based on station range
        if self.station_max == self.station_min:
            ratio = 0
        else:
            ratio = (station_value - self.station_min) / (self.station_max - self.station_min)
        
        spine_x = self.spine_x_min + ratio * (self.spine_x_max - self.spine_x_min)
        spine_y = self.spine_y_min + ratio * (self.spine_y_max - self.spine_y_min)
        
        return {'spine_x': spine_x, 'spine_y': spine_y, 'rotation_angle': 0}
    
    def _get_section_3d_data(self, section: Dict, spine_match: Dict) -> Dict:
        """
        Transform section data to 3D coordinates using V4's correct transformation
        """
        station_value = section.get('station_value', 0)
        station_name = section.get('station_name', '')
        
        # Reference point (L1 intersection)
        l1_ref = section.get('l1_ref_point', {})
        ref_x = l1_ref.get('x', 0)
        ref_y = l1_ref.get('y', 0)
        
        # Spine parameters
        spine_x = spine_match.get('spine_x', 0)
        spine_y = spine_match.get('spine_y', 0)
        rotation_angle = spine_match.get('rotation_angle', 0)
        
        result = {
            'station_value': station_value,
            'station_name': station_name,
            'spine_x': spine_x,
            'spine_y': spine_y,
            'rotation_angle': rotation_angle,
            'dmx_3d': None,
            'trench_3d': None,
            'geological_polys': []
        }
        
        # Transform DMX points
        dmx_points = section.get('dmx_points', [])
        if dmx_points and len(dmx_points) > 0:
            dmx_3d = []
            for pt in dmx_points:
                # Handle nested list structure
                if isinstance(pt[0], list):
                    pt = pt[0]
                
                cad_x, cad_y = pt[0], pt[1]
                eng_x, eng_y, z = transform_to_spine_aligned(
                    cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                )
                dmx_3d.append([eng_x, eng_y, z])
            
            result['dmx_3d'] = np.array(dmx_3d)
        
        # Transform overbreak points (trench)
        overbreak_points = section.get('overbreak_points', [])
        if overbreak_points and len(overbreak_points) > 0:
            trench_3d = []
            for pt_group in overbreak_points:
                # Handle nested structure
                if isinstance(pt_group[0], list):
                    for pt in pt_group:
                        if isinstance(pt[0], list):
                            pt = pt[0]
                        cad_x, cad_y = pt[0], pt[1]
                        eng_x, eng_y, z = transform_to_spine_aligned(
                            cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                        )
                        trench_3d.append([eng_x, eng_y, z])
                else:
                    cad_x, cad_y = pt_group[0], pt_group[1]
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    trench_3d.append([eng_x, eng_y, z])
            
            result['trench_3d'] = np.array(trench_3d)
        
        # Transform geological polygons (fill_boundaries)
        fill_boundaries = section.get('fill_boundaries', {})
        for layer_name, polygons in fill_boundaries.items():
            category = categorize_layer(layer_name)
            if category is None:
                continue
            
            for poly_points in polygons:
                if not poly_points or len(poly_points) < 3:
                    continue
                
                poly_3d = []
                for pt in poly_points:
                    if isinstance(pt[0], list):
                        pt = pt[0]
                    
                    cad_x, cad_y = pt[0], pt[1]
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    poly_3d.append([eng_x, eng_y, z])
                
                poly_3d = np.array(poly_3d)
                
                # Calculate properties
                area = calculate_polygon_area(poly_3d)
                centroid = calculate_centroid(poly_3d)
                
                result['geological_polys'].append({
                    'layer': layer_name,
                    'category': category,
                    'points': poly_3d,
                    'area': area,
                    'centroid': centroid
                })
        
        return result
    
    def build_dmx_ribbon(self) -> Dict:
        """Build DMX ribbon using V4 logic"""
        print("\n=== Building DMX Ribbon ===")
        
        section_data_list = []
        
        for section in self.sections:
            station_value = section.get('station_value', 0)
            spine_match = self._get_interpolated_spine_match(station_value)
            
            data = self._get_section_3d_data(section, spine_match)
            
            if data.get('dmx_3d') is not None:
                section_data_list.append(data)
        
        print(f"  Valid sections: {len(section_data_list)}")
        
        if len(section_data_list) < 2:
            return {'valid': False, 'vertices': [], 'faces': []}
        
        vertices = []
        faces = []
        
        for i, section in enumerate(section_data_list):
            dmx_3d = section['dmx_3d']
            spine_y = section['spine_y']
            
            # Resample DMX uniformly
            resampled = resample_line_uniform(dmx_3d, self.num_samples_dmx)
            
            for pt in resampled:
                vertices.append([pt[0], spine_y, pt[2]])
        
        n_per_section = self.num_samples_dmx
        n_sections = len(vertices) // n_per_section
        
        for i in range(n_sections - 1):
            base_a = i * n_per_section
            base_b = (i + 1) * n_per_section
            
            for j in range(n_per_section - 1):
                faces.append([base_a + j, base_b + j, base_a + j + 1])
                faces.append([base_a + j + 1, base_b + j, base_b + j + 1])
        
        print(f"  DMX ribbon: {len(vertices)} vertices, {len(faces)} faces")
        
        return {
            'valid': len(vertices) > 0,
            'vertices': np.array(vertices) if vertices else np.array([]),
            'faces': faces
        }
    
    def build_overbreak_ribbon(self) -> Dict:
        """Build overbreak trench using V4 segmented alignment"""
        print("\n=== Building Overbreak Trench ===")
        
        section_data_list = []
        
        for section in self.sections:
            station_value = section.get('station_value', 0)
            spine_match = self._get_interpolated_spine_match(station_value)
            
            data = self._get_section_3d_data(section, spine_match)
            
            if data.get('trench_3d') is not None:
                section_data_list.append(data)
        
        print(f"  Valid sections: {len(section_data_list)}")
        
        return generate_trench_ribbon(section_data_list, self.num_samples_dmx)
    
    def build_geological_volumes(self) -> Dict[str, Dict]:
        """Build geological volumes using V2 matching logic"""
        print("\n=== Building Geological Volumes ===")
        
        # Initialize results
        results = {}
        for cat_key in LAYER_CATEGORIES.keys():
            results[cat_key] = {
                'vertices': [],
                'faces': [],
                'volumes': 0
            }
        
        # Transform all sections
        section_data_list = []
        
        for section in self.sections:
            station_value = section.get('station_value', 0)
            spine_match = self._get_interpolated_spine_match(station_value)
            
            data = self._get_section_3d_data(section, spine_match)
            
            if len(data.get('geological_polys', [])) > 0:
                section_data_list.append(data)
        
        print(f"  Valid sections: {len(section_data_list)}")
        
        # Match and connect adjacent sections
        total_connections = 0
        
        for i in range(len(section_data_list) - 1):
            data_a = section_data_list[i]
            data_b = section_data_list[i + 1]
            
            polys_a = data_a['geological_polys']
            polys_b = data_b['geological_polys']
            
            connections = match_geological_polygons_with_similarity(
                polys_a, polys_b,
                self.distance_threshold,
                self.area_ratio_threshold
            )
            
            total_connections += len(connections)
            
            for p_a, p_b in connections:
                cat_key = p_a['category']
                
                verts, faces = generate_volume_mesh(
                    p_a['points'], p_b['points'],
                    self.num_samples_geo
                )
                
                # Offset indices
                offset = len(results[cat_key]['vertices'])
                for f in faces:
                    results[cat_key]['faces'].append([f[0] + offset, f[1] + offset, f[2] + offset])
                
                results[cat_key]['vertices'].extend(verts)
                results[cat_key]['volumes'] += 1
        
        print(f"  Total connections matched: {total_connections}")
        
        # Handle taper volumes (unmatched polygons)
        for i, data in enumerate(section_data_list):
            polys = data['geological_polys']
            
            if i < len(section_data_list) - 1:
                next_polys = section_data_list[i + 1]['geological_polys']
                matched_ids = set()
                
                connections = match_geological_polygons_with_similarity(
                    polys, next_polys,
                    self.distance_threshold,
                    self.area_ratio_threshold
                )
                
                for p_a, p_b in connections:
                    matched_ids.add(id(p_a))
                
                for p in polys:
                    if id(p) not in matched_ids:
                        cat_key = p['category']
                        verts, faces = generate_taper_volume(
                            p['points'], p['centroid'],
                            self.num_samples_geo
                        )
                        
                        offset = len(results[cat_key]['vertices'])
                        for f in faces:
                            results[cat_key]['faces'].append([f[0] + offset, f[1] + offset, f[2] + offset])
                        
                        results[cat_key]['vertices'].extend(verts)
                        results[cat_key]['volumes'] += 1
        
        # Convert to numpy arrays
        for cat_key in results:
            results[cat_key]['vertices'] = np.array(results[cat_key]['vertices'])
            print(f"  {LAYER_CATEGORIES[cat_key]['name_cn']}: {results[cat_key]['volumes']} volumes, "
                  f"{len(results[cat_key]['vertices'])} vertices")
        
        return results
    
    def export_to_html(self, output_path: str, category_data: Dict,
                       dmx_data: Dict, overbreak_data: Dict):
        """
        Export to Plotly HTML with V4 layer manager
        """
        print(f"\n=== Exporting to HTML ===")
        
        try:
            import plotly.graph_objects as go
        except ImportError:
            print("  [ERROR] plotly not available")
            return
        
        fig = go.Figure()
        
        # Add geological volumes
        for cat_key, data in category_data.items():
            verts = data['vertices']
            faces = data['faces']
            
            if len(verts) == 0 or len(faces) == 0:
                continue
            
            i_list = [f[0] for f in faces]
            j_list = [f[1] for f in faces]
            k_list = [f[2] for f in faces]
            
            mesh = go.Mesh3d(
                x=verts[:, 0],
                y=verts[:, 1],
                z=verts[:, 2],
                i=i_list,
                j=j_list,
                k=k_list,
                color=LAYER_CATEGORIES[cat_key]['color'],
                opacity=0.7,
                name=LAYER_CATEGORIES[cat_key]['name_cn'],
                hoverinfo='name',
                visible=True
            )
            fig.add_trace(mesh)
        
        # Add DMX ribbon
        if dmx_data['valid'] and len(dmx_data['vertices']) > 0:
            verts = dmx_data['vertices']
            faces = dmx_data['faces']
            
            if len(faces) > 0:
                i_list = [f[0] for f in faces]
                j_list = [f[1] for f in faces]
                k_list = [f[2] for f in faces]
                
                mesh = go.Mesh3d(
                    x=verts[:, 0],
                    y=verts[:, 1],
                    z=verts[:, 2],
                    i=i_list,
                    j=j_list,
                    k=k_list,
                    color='#3498db',
                    opacity=0.8,
                    name='DMX断面线',
                    hoverinfo='name',
                    visible=True
                )
                fig.add_trace(mesh)
        
        # Add overbreak trench
        if overbreak_data['valid'] and len(overbreak_data['vertices']) > 0:
            verts = overbreak_data['vertices']
            faces = overbreak_data['faces']
            
            if len(faces) > 0:
                i_list = [f[0] for f in faces]
                j_list = [f[1] for f in faces]
                k_list = [f[2] for f in faces]
                
                mesh = go.Mesh3d(
                    x=verts[:, 0],
                    y=verts[:, 1],
                    z=verts[:, 2],
                    i=i_list,
                    j=j_list,
                    k=k_list,
                    color='#e74c3c',
                    opacity=0.3,
                    name='超挖线梯形槽',
                    hoverinfo='name',
                    visible=True
                )
                fig.add_trace(mesh)
        
        # Layout with layer manager (V4 style)
        n_traces = len(fig.data)
        
        fig.update_layout(
            title='航道三维地质模型 - V4 DMX + V2地质层',
            scene=dict(
                xaxis_title='X (m)',
                yaxis_title='Y (里程 m)',
                zaxis_title='Z (高程 m)',
                aspectmode='data'
            ),
            showlegend=True,
            legend=dict(
                x=0.02,
                y=0.98,
                bgcolor='rgba(255,255,255,0.8)',
                bordercolor='rgba(0,0,0,0.3)',
                borderwidth=1,
                font=dict(size=12),
                title=dict(text='图层管理器', font=dict(size=14))
            ),
            updatemenus=[
                dict(
                    type='buttons',
                    showactive=True,
                    y=0.05,
                    x=0.02,
                    xanchor='left',
                    yanchor='bottom',
                    buttons=[
                        dict(
                            label='全部显示',
                            method='update',
                            args=[{'visible': [True] * n_traces}]
                        ),
                        dict(
                            label='仅地质层',
                            method='update',
                            args=[{'visible': [True, True, True, False, False] if n_traces >= 5 else [True] * n_traces}]
                        ),
                        dict(
                            label='仅DMX',
                            method='update',
                            args=[{'visible': [False, False, False, True, False] if n_traces >= 5 else [True] * n_traces}]
                        ),
                        dict(
                            label='仅超挖槽',
                            method='update',
                            args=[{'visible': [False, False, False, False, True] if n_traces >= 5 else [True] * n_traces}]
                        ),
                        dict(
                            label='DMX+超挖',
                            method='update',
                            args=[{'visible': [False, False, False, True, True] if n_traces >= 5 else [True] * n_traces}]
                        )
                    ]
                )
            ]
        )
        
        print(f"  Total traces: {n_traces}")
        fig.write_html(output_path)
        print(f"  Output: {output_path}")
    
    def build_and_export(self, output_path: str) -> str:
        """Complete build and export workflow"""
        if not self.load_data():
            return ""
        
        dmx_data = self.build_dmx_ribbon()
        overbreak_data = self.build_overbreak_ribbon()
        category_data = self.build_geological_volumes()
        
        self.export_to_html(output_path, category_data, dmx_data, overbreak_data)
        
        return output_path


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Combined Model Builder')
    parser.add_argument('--section-json', help='Section metadata JSON')
    parser.add_argument('--spine-json', help='Spine matches JSON')
    parser.add_argument('--output', help='Output HTML path')
    
    args = parser.parse_args()
    
    # Default paths for testing
    section_json = args.section_json or r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json'
    spine_json = args.spine_json or r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json'
    output_path = args.output or r'D:\断面算量平台\测试文件\combined_model_v4_correct_coords.html'
    
    print(f"Section JSON: {section_json}")
    print(f"Spine JSON: {spine_json}")
    print(f"Output: {output_path}")
    
    builder = CombinedModelBuilder(section_json, spine_json)
    builder.build_and_export(output_path)


if __name__ == '__main__':
    main()