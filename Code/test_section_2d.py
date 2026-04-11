# -*- coding: utf-8 -*-
"""
Test Section 2D - Verify each section's elements are correctly separated
"""

import ezdxf
import os
import math
import re
import matplotlib.pyplot as plt

class Section2DTest:
    """Test 2D section element extraction"""
    
    STATION_PATTERN = re.compile(r'K(\d+)\+(\d+)', re.IGNORECASE)
    
    def __init__(self, dxf_path):
        self.dxf_path = dxf_path
        self.doc = ezdxf.readfile(dxf_path)
        self.msp = self.doc.modelspace()
        self.layers = {l.dxf.name for l in self.doc.layers}
        
    def find_section_regions(self):
        """Find distinct section regions based on Y gaps
        
        Sections are separated by gaps in Y direction.
        We can detect these gaps to separate sections.
        """
        print("\n=== Finding Section Regions ===")
        
        # Get all L1 vertical lines (section markers)
        v_lines = []
        for e in self.msp.query('LINE[layer=="L1"]'):
            try:
                x_min = min(e.dxf.start.x, e.dxf.end.x)
                x_max = max(e.dxf.start.x, e.dxf.end.x)
                y_min = min(e.dxf.start.y, e.dxf.end.y)
                y_max = max(e.dxf.start.y, e.dxf.end.y)
                
                height = y_max - y_min
                width = x_max - x_min
                
                # Vertical lines (height > width)
                if height > width * 3:
                    v_lines.append({
                        'y_center': (y_min + y_max) / 2,
                        'y_min': y_min,
                        'y_max': y_max,
                        'x_center': (x_min + x_max) / 2,
                        'height': height
                    })
            except: pass
        
        # Sort by Y
        v_lines.sort(key=lambda e: e['y_center'], reverse=True)
        
        print(f"  Found {len(v_lines)} vertical L1 lines")
        
        # Group lines by Y proximity (within 100 units = same section)
        sections = []
        current_group = []
        last_y = None
        
        for line in v_lines:
            y = line['y_center']
            
            if last_y is None or abs(y - last_y) < 100:
                # Same section group
                current_group.append(line)
            else:
                # New section detected (Y gap > 100)
                if current_group:
                    sections.append(current_group)
                current_group = [line]
            
            last_y = y
        
        # Don't forget last group
        if current_group:
            sections.append(current_group)
        
        print(f"  Detected {len(sections)} section regions by Y gaps")
        
        # Calculate Y bounds for each section
        section_bounds = []
        for i, group in enumerate(sections):
            y_min = min(line['y_min'] for line in group)
            y_max = max(line['y_max'] for line in group)
            y_center = (y_min + y_max) / 2
            
            section_bounds.append({
                'section_id': i + 1,
                'y_min': y_min,
                'y_max': y_max,
                'y_center': y_center,
                'y_range': y_max - y_min,
                'num_v_lines': len(group)
            })
        
        return section_bounds
    
    def extract_section_elements_strict(self, y_min, y_max):
        """Extract elements STRICTLY within Y bounds
        
        CRITICAL: Only extract elements whose Y center is WITHIN section bounds
        """
        y_center = (y_min + y_max) / 2
        
        elements = {
            'dmx_lines': [],
            'layer_polygons': []
        }
        
        # Extract DMX lines - STRICT Y bound check
        for e in self.msp.query('LWPOLYLINE[layer=="DMX"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if not pts:
                    continue
                
                e_y_center = sum(p[1] for p in pts) / len(pts)
                e_y_min = min(p[1] for p in pts)
                e_y_max = max(p[1] for p in pts)
                
                # STRICT check: element Y center must be WITHIN section Y bounds
                if e_y_center >= y_min and e_y_center <= y_max:
                    elements['dmx_lines'].append({
                        'points': pts,
                        'y_center': e_y_center,
                        'num_points': len(pts)
                    })
            except: pass
        
        # Extract layer polygons
        for layer_name in self.layers:
            if '淤泥' in layer_name or '层' in layer_name:
                for e in self.msp.query(f'LWPOLYLINE[layer=="{layer_name}"]'):
                    try:
                        pts = [(p[0], p[1]) for p in e.get_points()]
                        if not pts:
                            continue
                        
                        e_y_center = sum(p[1] for p in pts) / len(pts)
                        
                        # STRICT check
                        if e_y_center >= y_min and e_y_center <= y_max:
                            elements['layer_polygons'].append({
                                'layer': layer_name,
                                'points': pts,
                                'y_center': e_y_center,
                                'num_points': len(pts)
                            })
                    except: pass
        
        return elements
    
    def plot_sections_2d(self, num_sections=5):
        """Plot each section separately in 2D to verify separation"""
        
        section_bounds = self.find_section_regions()
        
        if not section_bounds:
            print("ERROR: No sections found!")
            return
        
        # Take first N sections
        sections_to_plot = section_bounds[:num_sections]
        
        print(f"\n=== Plotting {len(sections_to_plot)} Sections in 2D ===")
        
        # Create figure with subplots
        fig, axes = plt.subplots(1, len(sections_to_plot), figsize=(20, 8))
        if len(sections_to_plot) == 1:
            axes = [axes]
        
        for i, bounds in enumerate(sections_to_plot):
            ax = axes[i]
            
            print(f"\n  Section {bounds['section_id']}:")
            print(f"    Y bounds: [{bounds['y_min']:.1f}, {bounds['y_max']:.1f}]")
            print(f"    Y range: {bounds['y_range']:.1f}")
            
            # Extract elements for this section
            elements = self.extract_section_elements_strict(
                bounds['y_min'], bounds['y_max']
            )
            
            print(f"    DMX lines: {len(elements['dmx_lines'])}")
            print(f"    Layer polygons: {len(elements['layer_polygons'])}")
            
            # Plot DMX lines (BLUE)
            for dmx in elements['dmx_lines']:
                xs = [p[0] for p in dmx['points']]
                ys = [p[1] for p in dmx['points']]
                ax.plot(xs, ys, 'b-', linewidth=2, alpha=0.8)
            
            # Plot layer polygons (different colors)
            colors = ['cyan', 'magenta', 'yellow', 'orange', 'green', 'purple']
            for j, poly in enumerate(elements['layer_polygons'][:20]):  # Limit to 20
                xs = [p[0] for p in poly['points']] + [poly['points'][0][0]]
                ys = [p[1] for p in poly['points']] + [poly['points'][0][1]]
                color = colors[j % len(colors)]
                ax.plot(xs, ys, color=color, linewidth=1, alpha=0.6)
            
            # Plot section frame (RED)
            # Estimate X range from DMX data
            all_x = []
            for dmx in elements['dmx_lines']:
                all_x.extend([p[0] for p in dmx['points']])
            
            if all_x:
                x_min = min(all_x) - 10
                x_max = max(all_x) + 10
            else:
                x_min, x_max = -100, 100
            
            # Draw frame rectangle
            frame_y_min = bounds['y_min']
            frame_y_max = bounds['y_max']
            ax.plot([x_min, x_max], [frame_y_min, frame_y_min], 'r-', linewidth=2)
            ax.plot([x_min, x_max], [frame_y_max, frame_y_max], 'r-', linewidth=2)
            ax.plot([x_min, x_min], [frame_y_min, frame_y_max], 'r-', linewidth=2)
            ax.plot([x_max, x_max], [frame_y_min, frame_y_max], 'r-', linewidth=2)
            
            # Set limits
            ax.set_xlim(x_min, x_max)
            ax.set_ylim(bounds['y_min'] - 20, bounds['y_max'] + 20)
            
            ax.set_title(f'Section {bounds["section_id"]}\nY=[{bounds["y_min"]:.0f}, {bounds["y_max"]:.0f}]')
            ax.set_xlabel('X')
            ax.set_ylabel('Y (CAD)')
            ax.grid(True, alpha=0.3)
            
            # Invert Y axis (CAD Y increases downward in some systems)
            ax.invert_yaxis()
        
        plt.tight_layout()
        plt.suptitle(f'2D Section Verification - {len(sections_to_plot)} Sections\n'
                     f'Each subplot should show ONLY ONE section', fontsize=14, y=1.02)
        plt.show()


def main():
    dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf'
    
    print("="*60)
    print("2D Section Verification Test")
    print("="*60)
    
    tester = Section2DTest(dxf_path)
    tester.plot_sections_2d(num_sections=5)


if __name__ == '__main__':
    main()