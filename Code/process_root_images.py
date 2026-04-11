import os
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
from pathlib import Path
import random

# 网络路径
BASE_DIR = Path(r"\\Beihai01\广西北海-测量资料\2、报测量公司文件\8、测量照片\设备照片\2026年一季度设备照片")

# 水印配置
COMPANY_NAME = "广西渤海农业发展有限公司"

# 各月份配置：目录名 -> (日期, 星期)
MONTH_CONFIG = {
    "1月": (datetime(2026, 1, 31), "星期六"),
    "2月": (datetime(2026, 2, 27), "星期五"),
    "3月": (datetime(2026, 3, 29), "星期天"),
}

# 根目录图片与月份的对应关系
IMAGE_MONTH_MAP = [
    ("0ca2a4462056b835181766eeb3d9837d.jpg", "1月"),
    ("cb97f8f5c22eb4e5942c8890f481215f.jpg", "2月"),
    ("dfbc8dd50a415d32e4783514e8fe74ef.jpg", "3月"),
]

def get_random_time():
    """生成16:00到17:00之间的随机时间"""
    random_minutes = random.randint(960, 1020)  # 16:00=960分钟, 17:00=1020分钟
    hours = random_minutes // 60
    minutes = random_minutes % 60
    return hours, minutes

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
                font_time = ImageFont.truetype(font_path, 240)  # 放大两倍: 120 -> 240
                font_info = ImageFont.truetype(font_path, 68)   # 放大两倍: 34 -> 68
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
    print("处理根目录下的图片...")
    print(f"基础目录: {BASE_DIR}")
    
    for img_filename, month_name in IMAGE_MONTH_MAP:
        img_path = BASE_DIR / img_filename
        
        if not img_path.exists():
            print(f"  [跳过] {img_filename} 文件不存在")
            continue
        
        date_obj, weekday_str = MONTH_CONFIG[month_name]
        output_dir = BASE_DIR / f"{month_name}_已加水印"
        output_dir.mkdir(exist_ok=True)
        
        try:
            pil_im = Image.open(str(img_path))
            if pil_im.mode != 'RGB':
                pil_im = pil_im.convert('RGB')
            
            hours, minutes = get_random_time()
            watermarked = add_watermark(pil_im, date_obj, weekday_str, hours, minutes)
            
            output_path = output_dir / img_filename
            watermarked.save(str(output_path), quality=95)
            
            print(f"  [OK] {img_filename} -> {month_name}_已加水印 ({date_obj.strftime('%Y-%m-%d')} {hours:02d}:{minutes:02d})")
            
        except Exception as e:
            print(f"  [ERR] {img_filename}: {str(e)}")
    
    print("\n完成！")

if __name__ == "__main__":
    main()