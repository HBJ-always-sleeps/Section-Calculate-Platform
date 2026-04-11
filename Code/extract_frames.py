"""
视频截帧程序
从视频中每0.5秒截取一帧，保存图片到同目录
"""
import cv2
import os
from pathlib import Path

def extract_frames(video_path, interval_seconds=0.5):
    """
    从视频中按时间间隔截取帧
    
    Args:
        video_path: 视频文件路径
        interval_seconds: 截取间隔（秒），默认0.5秒
    """
    video_path = Path(video_path)
    
    if not video_path.exists():
        print(f"错误：视频文件不存在 - {video_path}")
        return
    
    # 获取视频目录和文件名（不含扩展名）
    output_dir = video_path.parent
    video_name = video_path.stem
    
    # 创建输出子目录
    output_folder = output_dir / f"{video_name}_frames"
    output_folder.mkdir(exist_ok=True)
    
    print(f"视频文件: {video_path}")
    print(f"输出目录: {output_folder}")
    print(f"截取间隔: {interval_seconds}秒")
    
    # 打开视频
    cap = cv2.VideoCapture(str(video_path))
    
    if not cap.isOpened():
        print("错误：无法打开视频文件")
        return
    
    # 获取视频信息
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    
    print(f"视频FPS: {fps}")
    print(f"总帧数: {total_frames}")
    print(f"视频时长: {duration:.2f}秒")
    
    # 计算截取间隔的帧数
    frame_interval = int(fps * interval_seconds)
    print(f"每{interval_seconds}秒截取一帧，间隔{frame_interval}帧")
    
    frame_count = 0
    saved_count = 0
    
    while True:
        ret, frame = cap.read()
        
        if not ret:
            break
        
        # 每隔指定帧数保存一帧
        if frame_count % frame_interval == 0:
            # 计算当前时间戳
            timestamp = frame_count / fps
            output_path = output_folder / f"{video_name}_frame_{saved_count:04d}_t{timestamp:.1f}s.jpg"
            cv2.imwrite(str(output_path), frame)
            saved_count += 1
            print(f"已保存: {output_path.name}")
        
        frame_count += 1
    
    cap.release()
    print(f"\n完成！共保存 {saved_count} 张图片到: {output_folder}")

if __name__ == "__main__":
    video_path = r"D:\设备照片\202603261719.mp4"
    extract_frames(video_path, interval_seconds=0.5)