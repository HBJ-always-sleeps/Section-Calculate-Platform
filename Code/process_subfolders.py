import os
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timedelta
from pathlib import Path
import random

# 网络路径
BASE_DIR = Path(r"\\Beihai01\广西北海-测量资料\2、报测量公司文件\8、测量照片\设备照片\2026年一季度设备照片")

# 水印配置
COMPANY_NAME = "广西渤海农业发展有限公司"

# 各月份配置：目录名 -> (日期调早一天, 星期)
# 原日期: 1月31日, 2月27日, 3月29日 → 调早一天
MONTH_CONFIG = {
    "1月": (datetime(2026, 1, 30), "星期五"),   # 1月31日 → 1月30日
    "2月": (datetime(2026, 2, 26), "星期四"),   # 2月27日 → 2月26日
    "3月": (datetime(2026, 3, 28), "星期六"),   # 3月29日 → 3月28日
}

# 子文件夹配置：子文件夹名 -> 月份
SUBFOLDER_MAP = {
    "1月\\1": "1月",
    "2月\\2": "2月",
    "3月\\3": "3月",
}

def get_start_time():
    """生成15:00到16:00之间的随机起始时间"""
    random_minutes = random.randint(900, 960)  # 15:00=900分钟, 16:00=960分钟
    hours = random_minutes // 60
    minutes = random_minutes % 60
    return hours, minutes

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
                font_time = ImageFont.truetype(font_path, 240)  # 放大两倍
                font_info = ImageFont.truetype(font_path, 68)   # 放大两倍
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

def process_subfolder(subfolder_path, month_name):
    """处理子文件夹中的所有图片"""
    date_obj, weekday_str = MONTH_CONFIG[month_name]
    input_dir = BASE_DIR / subfolder_path
    output_dir = BASE_DIR / f"{month_name}_已加水印"
    
    if not input_dir.exists():
        print(f"  [跳过] 目录不存在: {input_dir}")
        return 0
    
    output_dir.mkdir(exist_ok=True)
    
    print(f"\n{'='*50}")
    print(f"处理目录: {subfolder_path}")
    print(f"日期: {date_obj.strftime('%Y-%m-%d')} {weekday_str}")
    print(f"输入: {input_dir}")
    print(f"输出: {output_dir}")
    
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}
    
    # 获取所有图片文件并排序
    image_files = []
    for filename in os.listdir(str(input_dir)):
        if any(filename.lower().endswith(ext) for ext in image_extensions):
            image_files.append(filename)
    
    image_files.sort()  # 按文件名排序
    
    if not image_files:
        print("  没有找到图片文件")
        return 0
    
    # 第一张照片随机时间
    start_hours, start_minutes = get_start_time()
    print(f"  起始时间: {start_hours:02d}:{start_minutes:02d}")
    
    processed = 0
    for idx, filename in enumerate(image_files):
        img_path = input_dir / filename
        
        try:
            pil_im = Image.open(str(img_path))
            if pil_im.mode != 'RGB':
                pil_im = pil_im.convert('RGB')
            
            # 每张照片间隔一分钟
            hours, minutes = increment_time(start_hours, start_minutes, idx)
            watermarked = add_watermark(pil_im, date_obj, weekday_str, hours, minutes)
            
            output_path = output_dir / filename
            watermarked.save(str(output_path), quality=95)
            
            processed += 1
            print(f"  [OK] {filename} ({hours:02d}:{minutes:02d})")
            
        except Exception as e:
            print(f"  [ERR] {filename}: {str(e)}")
    
    return processed

def main():
    print("处理子文件夹中的图片...")
    print(f"基础目录: {BASE_DIR}")
    print("配置: 日期调早一天, 时间调早一小时(15:00-16:00)")
    
    total = 0
    for subfolder, month_name in SUBFOLDER_MAP.items():
        count = process_subfolder(subfolder, month_name)
        total += count
    
    print(f"\n{'='*50}")
    print(f"全部完成！共处理 {total} 张图片")

if __name__ == "__main__":
    main()