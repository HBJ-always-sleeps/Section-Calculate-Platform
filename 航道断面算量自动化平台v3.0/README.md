<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# 航道断面算量自动化平台

一个用于航道断面算量自动化的桌面应用平台，提供五大核心功能模块。

## 功能模块

- **断面合并** - 合并多个断面线图层
- **批量粘贴** - 批量粘贴断面数据
- **快速填充** - 快速填充断面区域
- **分类算量** - 分类计算断面面积
- **分层算量** - 按高程分层计算

## 技术栈

- **前端**: React 19 + TypeScript + Tailwind CSS + Motion
- **后端**: Express.js
- **构建工具**: Vite

## 运行方式

**前置条件:** Node.js 18+

1. 安装依赖:
   ```bash
   npm install
   ```

2. 启动开发服务器:
   ```bash
   npm run dev
   ```

3. 打开浏览器访问: http://localhost:3000

## API 接口

| 接口 | 方法 | 描述 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/upload` | POST | 上传 DXF 文件 |
| `/api/task/:type` | POST | 执行任务 (autoline/autopaste/autohatch/autoclassify/autocut) |

## 构建生产版本

```bash
npm run build
npm run preview