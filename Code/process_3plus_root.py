import os
import random
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
from pathlib import Path
import time

# 网络路径
BASE_DIR = Path(r"\\Beihai01\广西北海-测量资料\2、报测量公司文件\8、测量照片\设备照片\2026年一季度设备照片")
INPUT_DIR = BASE_DIR / "3+"
OUTPUT_DIR = BASE_DIR / "3月_已加水印"

# 水印配置
COMPANY_NAME = "广西渤海农业发展有限公司"
DATE = datetime(2026, 4, 2)
WEEKDAY = "星期四"

def get_modification_time(filepath):
    """获取文件的修改时间戳"""
    return os.path.getmtime(str(filepath))

def increment_time(hours, minutes, offset_minutes):
    """增加指定分钟数"""
    total_minutes = hours * 60 + minutes + offset_minutes
    new_hours = total_minutes // 60
    new_minutes = total_minutes % 60
    return new_hours, new_minutes

def add_watermark(pil_im, date_obj, weekday_str, hours, minutes):
    """添加水印"""
    draw = ImageDraw.Draw(pil_im)
    w, h = pil_im.size
    
    time_str = f"{hours:02d}:{minutes:02d}"
    date_str = date_obj.strftime("%Y-%m-%d")
    
    font_paths = [
        'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/msyhbd.ttc',
        'C:/Windows/Fonts/simhei.ttf',
    ]
    
    font_time = None
    font_info = None
    
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                font_time = ImageFont.truetype(font_path, 240)
                font_info = ImageFont.truetype(font_path, 68)
                break
            except:
                continue
    
    if font_time is None:
        font_time = ImageFont.load_default()
        font_info = ImageFont.load_default()
    
    bottom_margin = int(h * 0.055)
    
    date_text = f"{date_str} {weekday_str}"
    bbox_date = draw.textbbox((0, 0), date_text, font=font_info)
    date_width = bbox_date[2] - bbox_date[0]
    date_height = bbox_date[3] - bbox_date[1]
    
    bbox_company = draw.textbbox((0, 0), COMPANY_NAME, font=font_info)
    company_width = bbox_company[2] - bbox_company[0]
    company_height = bbox_company[3] - bbox_company[1]
    
    icon_width = 40
    line_spacing = 40
    icon_company_spacing = 16
    line_width = date_width + line_spacing + icon_width + icon_company_spacing + company_width
    line_x = (w - line_width) // 2
    
    line_y = h - max(date_height, company_height) - bottom_margin
    
    date_x = line_x
    date_y = line_y
    icon_x = line_x + date_width + line_spacing + icon_width // 2
    icon_y = line_y + company_height // 2
    company_x = icon_x + icon_width // 2 + icon_company_spacing
    company_y = line_y
    
    bbox_time = draw.textbbox((0, 0), time_str, font=font_time)
    time_width = bbox_time[2] - bbox_time[0]
    time_height = bbox_time[3] - bbox_time[1]
    time_x = (w - time_width) // 2
    time_y = line_y - time_height - int(h * 0.025)
    
    draw.text((time_x, time_y), time_str, font=font_time, fill=(255, 255, 255))
    draw.text((date_x, date_y), date_text, font=font_info, fill=(255, 255, 255))
    
    circle_radius = 12
    draw.ellipse([icon_x - circle_radius, icon_y - circle_radius - 8, 
                  icon_x + circle_radius, icon_y + circle_radius - 8], 
                 fill=(255, 0, 0), outline=(255, 255, 255), width=4)
    
    triangle_points = [
        (icon_x, icon_y + circle_radius + 12),
        (icon_x - 8, icon_y - 4),
        (icon_x + 8, icon_y - 4)
    ]
    draw.polygon(triangle_points, fill=(255, 0, 0))
    draw.line([triangle_points[0], triangle_points[1]], fill=(255, 255, 255), width=4)
    draw.line([triangle_points[0], triangle_points[2]], fill=(255, 255, 255), width=4)
    
    draw.text((company_x, company_y), COMPANY_NAME, font=font_info, fill=(255, 255, 255))
    
    return pil_im

def main():
    print("处理3+根目录的图片...")
    print(f"基础目录: {BASE_DIR}")
    print(f"输出目录: {OUTPUT_DIR}")
    
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}
    
    # 获取所有图片文件
    image_files = []
    for filename in os.listdir(str(INPUT_DIR)):
        filepath = INPUT_DIR / filename
        if filepath.is_file() and any(filename.lower().endswith(ext) for ext in image_extensions):
            image_files.append((filename, get_modification_time(filepath)))
    
    if not image_files:
        print("没有找到图片文件")
        return
    
    # 按修改时间排序（从新到旧）
    image_files.sort(key=lambda x: x[1], reverse=True)
    
    print(f"\n找到 {len(image_files)} 张图片（按修改时间排序）：")
    for i, (filename, mtime) in enumerate(image_files):
        mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
        print(f"  {i+1}. {filename} (修改时间: {mtime_str})")
    
    # 时间段配置
    # 通电类时间：16:39-16:51
    electric_min = 16 * 60 + 39  # 16:39
    electric_max = 16 * 60 + 51  # 16:51
    
    # 码类时间：17:45开始，间隔1分钟
    code_start = (17, 45)
    
    processed = 0
    for idx, (filename, mtime) in enumerate(image_files):
        img_path = INPUT_DIR / filename
        
        try:
            pil_im = Image.open(str(img_path))
            if pil_im.mode != 'RGB':
                pil_im = pil_im.convert('RGB')
            
            # 最新修改的图片用通电类时间
            if idx == 0:
                # 随机时间在16:39-16:51之间
                rand_minutes = random.randint(electric_min, electric_max)
                hours = rand_minutes // 60
                minutes = rand_minutes % 60
                time_type = "通电"
            else:
                # 其他图片用码类时间，间隔1分钟
                hours, minutes = increment_time(code_start[0], code_start[1], idx - 1)
                time_type = "码"
            
            watermarked = add_watermark(pil_im, DATE, WEEKDAY, hours, minutes)
            
            output_path = OUTPUT_DIR / filename
            watermarked.save(str(output_path), quality=95)
            
            processed += 1
            print(f"  [{time_type}] {filename} -> {hours:02d}:{minutes:02d}")
            
        except Exception as e:
            print(f"  [ERR] {filename}: {str(e)}")
    
    print(f"\n{'='*50}")
    print(f"全部完成！共处理 {processed} 张图片")

if __name__ == "__main__":
    main()