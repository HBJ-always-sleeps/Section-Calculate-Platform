# -*- coding: utf-8 -*-
"""
三维图层展示 - 基于已验证的断面检测逻辑

关键经验（来自memory）：
1. 代码位置：Code/bim_model_builder.py（245断面完美匹配）
2. 自适应缩放比例检测：通过断面线平均长度和间距推断
3. 自适应匹配容差：500 * scale_factor
4. 相交检测代替中心点包含：Y轴向下扩展10单位
5. DXF坐标系：Y向下为正（CAD惯例）
6. 显示坐标系：Y向上为正（matplotlib惯例）
7. 正确转换：display_y = -y（取反！）

作者: @黄秉俊
日期: 2026-03-30
"""

import ezdxf
import os
import math
import re
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import numpy as np
from typing import List, Dict, Tuple, Optional
from shapely.geometry import Polygon, LineString, box, Point

class SectionDetectorVerified:
    """断面检测器 - 采用已验证的bim_model_builder逻辑（245断面匹配）"""
    
    STATION_PATTERN = re.compile(r'(\d+\+\d+)')
    
    def __init__(self, msp, doc):
        self.msp = msp
        self.doc = doc
        self.scale_factor = 1.0
        
    def detect_sections(self) -> List[Dict]:
        print("  检测断面（已验证逻辑）...")
        
        dmx_list = self._get_dmx_sections()
        print(f"    DMX断面线: {len(dmx_list)}条")
        if not dmx_list:
            return []
        
        self.scale_factor = self._detect_scale_factor(dmx_list)
        print(f"    缩放比例: {self.scale_factor:.4f}")
        
        station_texts = self._get_station_texts()
        print(f"    桩号文本: {len(station_texts)}个")
        
        overbreak_lines = self._get_overbreak_lines()
        print(f"    超挖线: {len(overbreak_lines)}条")
        
        fill_data = self._get_fill_boundaries()
        print(f"    填充图层: {len(fill_data)}个")
        
        station_groups = self._group_by_station(dmx_list, station_texts)
        print(f"    桩号分组数: {len(station_groups)}个")
        
        sections = []
        for group_info in station_groups:
            dmx_group = group_info['dmx_group']
            all_x_min = min(d['x_min'] for d in dmx_group)
            all_x_max = max(d['x_max'] for d in dmx_group)
            all_y_min = min(d['y_min'] for d in dmx_group)
            all_y_max = max(d['y_max'] for d in dmx_group)
            y_center = (all_y_min + all_y_max) / 2
            
            all_dmx_pts = []
            for d in dmx_group:
                all_dmx_pts.extend(d['pts'])
            
            section = {
                'station_name': group_info['station_name'],
                'station_value': group_info['station_value'],
                'x_min': all_x_min, 'x_max': all_x_max,
                'y_min': all_y_min, 'y_max': all_y_max,
                'y_center': y_center,
                'dmx_points': all_dmx_pts,
                'overbreak_points': self._match_overbreak(dmx_group, overbreak_lines),
                'fill_boundaries': self._match_fills(dmx_group, fill_data)
            }
            sections.append(section)
        
        sections.sort(key=lambda s: -s['y_center'])
        print(f"    最终断面数: {len(sections)}个")
        return sections
    
    def _detect_scale_factor(self, dmx_list: List[Dict]) -> float:
        try:
            if len(dmx_list) < 3:
                return 1.0
            avg_length = sum(d['line'].length for d in dmx_list) / len(dmx_list)
            y_centers = sorted([d['y_center'] for d in dmx_list], reverse=True)
            gaps = [y_centers[i] - y_centers[i+1] for i in range(len(y_centers)-1)] if len(y_centers) >= 2 else [100]
            avg_gap = sum(gaps) / len(gaps)
            length_scale = avg_length / 200.0
            gap_scale = avg_gap / 100.0
            scale = (length_scale + gap_scale) / 2
            return max(0.1, min(10.0, scale))
        except:
            return 1.0
    
    def _group_by_station(self, dmx_list: List[Dict], station_texts: List[Dict]) -> List[Dict]:
        match_tolerance = 500 * self.scale_factor
        sorted_stations = sorted(station_texts, key=lambda s: s['y'], reverse=True)
        sorted_dmx = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)
        groups, used_dmx = [], set()
        
        for station in sorted_stations:
            best_idx, best_dist = None, float('inf')
            for i, dmx in enumerate(sorted_dmx):
                if i in used_dmx:
                    continue
                y_dist = abs(dmx['y_center'] - station['y'])
                x_dist = abs((dmx['x_min'] + dmx['x_max']) / 2 - station['x'])
                total_dist = math.sqrt(y_dist**2 + x_dist**2 * 0.5)
                if total_dist < best_dist:
                    best_dist, best_idx = total_dist, i
            
            if best_idx is not None and best_dist < match_tolerance:
                used_dmx.add(best_idx)
                groups.append({
                    'station_name': station['text'],
                    'station_value': station['value'],
                    'dmx_group': [sorted_dmx[best_idx]]
                })
        
        unmatched = [d for i, d in enumerate(sorted_dmx) if i not in used_dmx]
        for cluster in self._cluster_by_y(unmatched):
            avg_y = sum(d['y_center'] for d in cluster) / len(cluster)
            groups.append({'station_name': f"S{int(avg_y)}", 'station_value': int(avg_y), 'dmx_group': cluster})
        return groups
    
    def _cluster_by_y(self, dmx_list: List[Dict]) -> List[List[Dict]]:
        if not dmx_list:
            return []
        sorted_dmx = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)
        heights = [d['y_max'] - d['y_min'] for d in sorted_dmx]
        threshold = sorted(heights)[len(heights)//2] * 1.5 if heights else 100
        clusters = [[sorted_dmx[0]]]
        for i in range(1, len(sorted_dmx)):
            if abs(sorted_dmx[i]['y_center'] - sorted_dmx[i-1]['y_center']) < threshold:
                clusters[-1].append(sorted_dmx[i])
            else:
                clusters.append([sorted_dmx[i]])
        return clusters
    
    def _get_dmx_sections(self) -> List[Dict]:
        dmx_list = []
        for e in self.msp.query('LWPOLYLINE[layer=="DMX"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if len(pts) >= 2:
                    dmx_list.append({
                        'pts': pts, 'line': LineString(pts),
                        'x_min': min(p[0] for p in pts), 'x_max': max(p[0] for p in pts),
                        'y_min': min(p[1] for p in pts), 'y_max': max(p[1] for p in pts),
                        'y_center': (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
                    })
            except: pass
        return dmx_list
    
    def _get_station_texts(self) -> List[Dict]:
        stations = []
        for e in self.msp.query('TEXT MTEXT'):
            try:
                txt = (e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text).upper()
                match = self.STATION_PATTERN.search(txt)
                if match:
                    x, y = e.dxf.insert.x, e.dxf.insert.y
                    sid = match.group(1)
                    value = int("".join(re.findall(r'\d+', sid)))
                    stations.append({'text': sid, 'value': value, 'x': x, 'y': y})
            except: pass
        return stations
    
    def _get_overbreak_lines(self) -> List[LineString]:
        return [LineString([(p[0], p[1]) for p in e.get_points()]) for e in self.msp.query('LWPOLYLINE[layer=="超挖线"]') if len(list(e.get_points())) >= 2]
    
    def _get_fill_boundaries(self) -> Dict[str, List]:
        fill_data = {}
        for layer_name in [l.dxf.name for l in self.doc.layers]:
            if any(k in layer_name for k in ['填充', '淤泥', '黏土', '砂', '碎石', '填土', '层']) or layer_name.lower().startswith('nonem'):
                boundaries = []
                for e in self.msp.query(f'LWPOLYLINE[layer=="{layer_name}"]'):
                    try:
                        pts = [(p[0], p[1]) for p in e.get_points()]
                        if len(pts) >= 3:
                            boundaries.append(pts)
                    except: pass
                if boundaries:
                    fill_data[layer_name] = boundaries
        return fill_data
    
    def _match_overbreak(self, dmx_group: List[Dict], overbreak_lines: List[LineString]) -> List:
        all_x = [d['x_min'] for d in dmx_group] + [d['x_max'] for d in dmx_group]
        all_y = [d['y_min'] for d in dmx_group] + [d['y_max'] for d in dmx_group]
        group_box = box(min(all_x) - 10, min(all_y) - 20, max(all_x) + 10, max(all_y) + 10)
        return [list(line.coords) for line in overbreak_lines if group_box.intersects(line)]
    
    def _match_fills(self, dmx_group: List[Dict], fill_data: Dict) -> Dict:
        all_x = [d['x_min'] for d in dmx_group] + [d['x_max'] for d in dmx_group]
        all_y = [d['y_min'] for d in dmx_group] + [d['y_max'] for d in dmx_group]
        group_box = box(min(all_x) - 10, min(all_y) - 20, max(all_x) + 10, max(all_y) + 10)
        matched = {}
        for layer_name, boundaries in fill_data.items():
            layer_matched = [b for b in boundaries if len(b) >= 3 and group_box.intersects(Polygon(b))]
            if layer_matched:
                matched[layer_name] = layer_matched
        return matched


class Layer3DVisualizer:
    """三维图层可视化器"""
    
    def __init__(self, dxf_path: str):
        self.dxf_path = dxf_path
        self.doc = ezdxf.readfile(dxf_path)
        self.msp = self.doc.modelspace()
        
    def build_3d_model(self, num_sections: int = 10) -> Dict:
        print("\n" + "="*60)
        print("构建三维模型（已验证的断面检测逻辑）")
        print("="*60)
        
        detector = SectionDetectorVerified(self.msp, self.doc)
        sections = detector.detect_sections()
        if not sections:
            return None
        
        sections = sections[:num_sections]
        print(f"\n取前{len(sections)}个断面")
        
        model_data = {'metadata': {'scale_factor': detector.scale_factor}, 'sections': []}
        norm = 10
        
        for i, sec in enumerate(sections):
            cad_y = sec['y_center']
            print(f"\n断面 {i+1}: {sec['station_name']} (CAD Y={cad_y:.1f})")
            
            section_3d = {
                'section_index': i + 1, 'station_name': sec['station_name'],
                'cad_y': cad_y,
                'dmx_3d': [(pt[0]/norm, -pt[1]/norm, cad_y) for pt in sec['dmx_points']],
                'overbreak_3d': [[(pt[0]/norm, -pt[1]/norm, cad_y) for pt in ob] for ob in sec['overbreak_points']],
                'fills_3d': {name: [[(pt[0]/norm, -pt[1]/norm, cad_y) for pt in b] for b in bounds] for name, bounds in sec['fill_boundaries'].items()}
            }
            model_data['sections'].append(section_3d)
        
        return model_data
    
    def visualize_3d(self, model_data: Dict):
        print("\n=== 三维可视化 ===")
        fig = plt.figure(figsize=(16, 12))
        ax = fig.add_subplot(111, projection='3d')
        colors = plt.cm.tab20.colors
        
        for sec in model_data['sections']:
            z = sec['cad_y']
            if sec['dmx_3d']:
                pts = np.array(sec['dmx_3d'])
                ax.plot(pts[:, 0], pts[:, 1], pts[:, 2], 'b-', lw=2.5)
            for ob in sec['overbreak_3d']:
                if len(ob) >= 2:
                    pts = np.array(ob)
                    ax.plot(pts[:, 0], pts[:, 1], pts[:, 2], 'r--', lw=2)
            for name, bounds in sec['fills_3d'].items():
                ci = hash(name) % len(colors)
                for b in bounds:
                    if len(b) >= 3:
                        pts = np.array(b + [b[0]])
                        ax.plot(pts[:, 0], pts[:, 1], pts[:, 2], color=colors[ci], lw=1.5, alpha=0.7)
            ax.text(15, 0, z, sec['station_name'], fontsize=9)
        
        zs = [sec['cad_y'] for sec in model_data['sections']]
        ax.plot([0]*len(zs), [0]*len(zs), zs, 'g-', lw=4, label='航道中心线')
        
        ax.set_xlabel('X (宽度)'); ax.set_ylabel('Y (深度, -CAD_Y)'); ax.set_zlabel('Z (桩号)')
        ax.set_title(f'三维断面模型 (前{len(model_data["sections"])}断面)\nY = -CAD_Y (取反)')
        ax.legend(); ax.view_init(elev=20, azim=45)
        
        output_path = r'D:\断面算量平台\测试文件\test_3d_layers_verified.png'
        plt.savefig(output_path, dpi=150)
        print(f"\n保存: {output_path}")
        plt.show()
        return output_path


def main():
    dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf'
    print("="*60)
    print("三维图层展示 - 已验证断面检测逻辑")
    print("关键: 自适应容差=500*scale, Y=-CAD_Y")
    print("="*60)
    
    visualizer = Layer3DVisualizer(dxf_path)
    model_data = visualizer.build_3d_model(num_sections=10)
    if model_data:
        visualizer.visualize_3d(model_data)

if __name__ == '__main__':
    main()