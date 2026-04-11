# -*- coding: utf-8 -*-
"""
Section 3D Builder - Build 3D model from DXF section data

CORRECTED v2: Use CAD Y position as actual 3D Y coordinate
- Mileage is LABEL only (for display)
- Same mileage CAN have multiple sections at different CAD Y positions
- These are DIFFERENT sections (different measurements/parts)

Author: @HBJ
Date: 2026-03-28
"""

import ezdxf
import os
import math
import re
import json

class Section3DBuilder:
    """Build 3D section model from DXF using CAD Y as actual coordinate"""
    
    STATION_PATTERN = re.compile(r'K(\d+)\+(\d+)', re.IGNORECASE)
    
    def __init__(self, dxf_path):
        self.dxf_path = dxf_path
        self.doc = ezdxf.readfile(dxf_path)
        self.msp = self.doc.modelspace()
        self.layers = {l.dxf.name for l in self.doc.layers}
        
    def extract_station_text(self, bp_cad_x, bp_cad_y):
        """Extract station text near base point"""
        for e in self.msp.query('TEXT'):
            try:
                txt = e.dxf.text.strip()
                if abs(e.dxf.insert.x - bp_cad_x) < 200 and abs(e.dxf.insert.y - bp_cad_y) < 200:
                    match = self.STATION_PATTERN.search(txt)
                    if match:
                        return int(match.group(1)) * 1000 + int(match.group(2))
            except: pass
        
        for e in self.msp.query('MTEXT'):
            try:
                txt = e.plain_text().strip()
                if abs(e.dxf.insert.x - bp_cad_x) < 200 and abs(e.dxf.insert.y - bp_cad_y) < 200:
                    match = self.STATION_PATTERN.search(txt)
                    if match:
                        return int(match.group(1)) * 1000 + int(match.group(2))
            except: pass
        return None
    
    def extract_l1_base_points(self):
        """Extract L1 base points - DO NOT deduplicate by mileage"""
        print("\n=== Extract L1 Base Points (CAD Y preserved) ===")
        
        line_entities = []
        for e in self.msp.query('LINE[layer=="L1"]'):
            try:
                x_min = min(e.dxf.start.x, e.dxf.end.x)
                x_max = max(e.dxf.start.x, e.dxf.end.x)
                y_min = min(e.dxf.start.y, e.dxf.end.y)
                y_max = max(e.dxf.start.y, e.dxf.end.y)
                line_entities.append({
                    'x_min': x_min, 'x_max': x_max,
                    'y_min': y_min, 'y_max': y_max,
                    'width': x_max - x_min,
                    'height': y_max - y_min,
                    'y_center': (y_min + y_max) / 2,
                    'x_center': (x_min + x_max) / 2
                })
            except: pass
        
        horizontal_lines = [l for l in line_entities if l['width'] > l['height'] * 3]
        vertical_lines = [l for l in line_entities if l['height'] > l['width'] * 3]
        
        print(f"  Horizontal: {len(horizontal_lines)}, Vertical: {len(vertical_lines)}")
        
        sorted_v = sorted(vertical_lines, key=lambda e: e['y_center'], reverse=True)
        sorted_h = sorted(horizontal_lines, key=lambda e: e['y_center'], reverse=True)
        
        base_points = []
        used_h = set()
        
        for idx, v in enumerate(sorted_v):
            best_h = None
            best_diff = float('inf')
            best_idx = -1
            
            for h_idx, h in enumerate(sorted_h):
                if h_idx in used_h:
                    continue
                diff = abs(h['y_center'] - v['y_center'])
                if diff < best_diff:
                    best_diff = diff
                    best_h = h
                    best_idx = h_idx
            
            if best_h and best_diff < 50:
                used_h.add(best_idx)
                mileage = self.extract_station_text(v['x_center'], v['y_center'])
                if mileage is None:
                    mileage = idx * 100
                
                base_points.append({
                    'ref_x': v['x_center'],
                    'ref_y': v['y_center'],  # CAD Y - preserved!
                    'depth': v['height'],
                    'top_width': best_h['width'],
                    'mileage': mileage  # LABEL only!
                })
        
        # Sort by CAD Y (not mileage!)
        base_points.sort(key=lambda bp: bp['ref_y'], reverse=True)
        
        print(f"  Matched: {len(base_points)}")
        for bp in base_points[:5]:
            print(f"    CAD Y={bp['ref_y']:.1f}, Mileage={bp['mileage']}m")
        
        return base_points
    
    def extract_section_elements(self, base_point):
        """Extract elements within Y bounds"""
        ref_x = base_point['ref_x']
        ref_y = base_point['ref_y']
        
        elements = {'dmx_lines': [], 'layer_polygons': []}
        
        for e in self.msp.query('LWPOLYLINE[layer=="DMX"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if not pts:
                    continue
                e_y = sum(p[1] for p in pts) / len(pts)
                if abs(e_y - ref_y) < 50:
                    rel_pts = [(p[0] - ref_x, p[1] - ref_y) for p in pts]
                    elements['dmx_lines'].append({'rel_points': rel_pts})
            except: pass
        
        for layer in self.layers:
            if '淤泥' in layer or '层' in layer:
                for e in self.msp.query(f'LWPOLYLINE[layer=="{layer}"]'):
                    try:
                        pts = [(p[0], p[1]) for p in e.get_points()]
                        if not pts:
                            continue
                        e_y = sum(p[1] for p in pts) / len(pts)
                        if abs(e_y - ref_y) < 50:
                            rel_pts = [(p[0] - ref_x, p[1] - ref_y) for p in pts]
                            elements['layer_polygons'].append({'layer': layer, 'rel_points': rel_pts})
                    except: pass
        
        return elements
    
    def build_3d_model_data(self, num_sections=10):
        """Build 3D model - Y = CAD Y position (NOT mileage!)"""
        print("\n" + "="*60)
        print("Building 3D Model (CAD Y as coordinate)")
        print("="*60)
        
        base_points = self.extract_l1_base_points()
        if not base_points:
            return None
        
        # Group by CAD Y (round to 50 units)
        grouped = {}
        for bp in base_points:
            y_key = round(bp['ref_y'] / 50) * 50
            if y_key not in grouped:
                grouped[y_key] = bp
        
        sections = list(grouped.values())
        sections.sort(key=lambda bp: bp['ref_y'], reverse=True)
        sections = sections[:num_sections]
        
        print(f"\n  Grouped: {len(base_points)} → {len(sections)} unique CAD Y")
        
        model_data = {
            'metadata': {
                'source_file': os.path.basename(self.dxf_path),
                'coordinate_system': 'Y=CAD position, mileage=LABEL'
            },
            'sections': []
        }
        
        for i, bp in enumerate(sections):
            cad_y = bp['ref_y']  # ACTUAL 3D Y coordinate!
            mileage = bp['mileage']  # LABEL only
            
            print(f"\n--- Section {i+1} ---")
            print(f"  CAD Y: {cad_y:.1f} (3D_Y)")
            print(f"  Mileage: {mileage}m (LABEL)")
            
            elements = self.extract_section_elements(bp)
            print(f"  DMX: {len(elements['dmx_lines'])}, Polygons: {len(elements['layer_polygons'])}")
            
            # Normalize: divide by 10
            norm = 10
            section_3d = {
                'section_index': i + 1,
                'cad_y': cad_y,
                'mileage': mileage,
                'frame_3d': self._calc_frame(bp, cad_y, norm),
                'dmx_lines_3d': [[(p[0]/norm, cad_y, p[1]/norm) for p in d['rel_points']] for d in elements['dmx_lines']],
                'layer_polygons_3d': [{'layer': p['layer'], 'pts': [(pt[0]/norm, cad_y, pt[1]/norm) for pt in p['rel_points']]} for p in elements['layer_polygons']]
            }
            model_data['sections'].append(section_3d)
        
        return model_data
    
    def _calc_frame(self, bp, cad_y, norm):
        hw = bp['top_width'] / 2 / norm
        d = bp['depth'] / norm
        return {
            'top_left': (-hw, cad_y, 0),
            'top_right': (hw, cad_y, 0),
            'bottom_left': (-hw, cad_y, -d),
            'bottom_right': (hw, cad_y, -d)
        }


def main():
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D
    
    dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf'
    
    print("Section 3D Builder (CORRECTED v2)")
    builder = Section3DBuilder(dxf_path)
    model_data = builder.build_3d_model_data(num_sections=10)
    
    if model_data:
        print("\n=== 3D Plot ===")
        fig = plt.figure(figsize=(14, 10))
        ax = fig.add_subplot(111, projection='3d')
        
        for sec in model_data['sections']:
            y = sec['cad_y']  # CAD Y!
            frame = sec['frame_3d']
            tl, tr, bl, br = frame['top_left'], frame['top_right'], frame['bottom_left'], frame['bottom_right']
            
            # Frame (red)
            for p1, p2 in [(tl,tr), (bl,br), (tl,bl), (tr,br)]:
                ax.plot([p1[0],p2[0]], [p1[1],p2[1]], [p1[2],p2[2]], 'r-', lw=2)
            
            # Centerline (green)
            ax.plot([0,0], [y,y], [0,bl[2]], 'g-', lw=3)
            ax.scatter(0, y, 0, c='green', s=80)
            
            # Mileage label
            m = sec['mileage']
            ax.text(8, y, 0, f'K{m//1000}+{m%1000}', fontsize=8)
            
            # DMX (blue)
            for pts in sec['dmx_lines_3d']:
                if len(pts) >= 2:
                    ax.plot([p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts], 'b-', lw=1.5)
            
            # Polygons (cyan)
            for poly in sec['layer_polygons_3d']:
                pts = poly['pts']
                if len(pts) >= 3:
                    xs = [p[0] for p in pts] + [pts[0][0]]
                    ys = [p[1] for p in pts] + [pts[0][1]]
                    zs = [p[2] for p in pts] + [pts[0][2]]
                    ax.plot(xs, ys, zs, 'c-', lw=1, alpha=0.6)
        
        # Centerline (all X=0)
        ys = [sec['cad_y'] for sec in model_data['sections']]
        ax.plot([0]*len(ys), ys, [0]*len(ys), 'g-', lw=4, label='Centerline')
        
        ax.set_xlabel('X (normalized)')
        ax.set_ylabel('Y (CAD position)')
        ax.set_zlabel('Z (normalized)')
        ax.set_title(f'3D Model (CAD Y)\n{len(model_data["sections"])} sections')
        ax.legend()
        plt.tight_layout()
        plt.show()


if __name__ == '__main__':
    main()