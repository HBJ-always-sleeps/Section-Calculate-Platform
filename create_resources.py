#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建资源文件"""

import base64
import os

# 读取图片
img_path = r'C:\Users\训教\Downloads\Gemini_Generated_Image_3db1n53db1n53db1.png'
print('图片存在:', os.path.exists(img_path))

with open(img_path, 'rb') as f:
    data = f.read()

print('图片大小:', len(data), '字节')

# 转为base64
b64_data = base64.b64encode(data).decode('utf-8')
print('Base64长度:', len(b64_data))

# 写入资源文件
output_path = os.path.join(os.path.dirname(__file__), 'platform_resources.py')
print('输出路径:', output_path)

with open(output_path, 'w', encoding='utf-8') as f:
    f.write('#!/usr/bin/env python3\n')
    f.write('# -*- coding: utf-8 -*-\n')
    f.write('"""平台资源文件 - 启动画面图片"""\n\n')
    f.write('# Base64编码的启动画面图片\n')
    f.write('SPLASH_IMAGE_BASE64 = """\n')
    for i in range(0, len(b64_data), 1000):
        f.write(b64_data[i:i+1000] + '\n')
    f.write('"""\n')

print('资源文件已创建!')
print('文件存在:', os.path.exists(output_path))