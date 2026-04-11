# 修改Y轴缩放因子
import os

f = 'bim_model_builder.py'
c = open(f, encoding='utf-8').read()

# 替换y_scale值
old = 'y_scale = 10.0  # 放大10倍，让深度更明显'
new = 'y_scale = 50.0  # 放大50倍，让深度更明显'

c = c.replace(old, new)

open(f, encoding='utf-8', mode='w').write(c)
print('Y轴缩放已修改为50倍')