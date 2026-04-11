import os
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
from pathlib import Path

# 图片路径
IMAGE_PATH = Path(r"\\Beihai01\广西北海-测量资料\2、报测量公司文件\8、测量照片\设备照片\2026年一季度设备照片\微信图片_20260403094722_953_53.jpg")

# 输出目录
OUTPUT_DIR = Path(r"\\Beihai01\广西北海-测量资料\2、报测量公司文件\8、测量照片\设备照片\2026年一季度设备照片\3月_已加水印")

# 水印配置
COMPANY_NAME = "广西渤海农业发展有限公司"

# 日期配置
DATE = datetime(2026, 4, 2)  # 2026年4月2日
HOURS = 17
MINUTES = 50
WEEKDAY = "星期四"  # 用户指定

def get_weekday(date_obj):
    """获取星期几的中文"""
    return WEEKDAY  # 使用用户指定的星期

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
    print("处理单张图片水印...")
    
    # 检查源文件
    if not IMAGE_PATH.exists():
        print(f"[错误] 文件不存在: {IMAGE_PATH}")
        return
    
    # 创建输出目录
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    # 获取星期几
    weekday_str = get_weekday(DATE)
    print(f"日期: {DATE.strftime('%Y-%m-%d')} {weekday_str}")
    print(f"时间: {HOURS:02d}:{MINUTES:02d}")
    
    try:
        pil_im = Image.open(str(IMAGE_PATH))
        if pil_im.mode != 'RGB':
            pil_im = pil_im.convert('RGB')
        
        watermarked = add_watermark(pil_im, DATE, weekday_str, HOURS, MINUTES)
        
        output_path = OUTPUT_DIR / IMAGE_PATH.name
        watermarked.save(str(output_path), quality=95)
        
        print(f"[成功] 已保存到: {output_path}")
        
    except Exception as e:
        print(f"[错误] 处理失败: {str(e)}")

if __name__ == "__main__":
    main()