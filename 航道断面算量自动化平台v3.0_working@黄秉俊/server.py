# -*- coding: utf-8 -*-
"""
航道断面算量自动化平台 v3.0 - 后端API服务
FastAPI 后端，提供 REST API 接口
"""

import os
import sys
import json
import shutil
import traceback
import tempfile
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 尝试导入引擎
try:
    import engine_cad
    ENGINE_AVAILABLE = True
    print("[OK] 引擎模块加载成功")
except ImportError as e:
    ENGINE_AVAILABLE = False
    print(f"[WARN] 引擎模块加载失败: {e}")

# ==================== FastAPI 应用 ====================
app = FastAPI(
    title="航道断面算量自动化平台 API",
    description="提供 DXF 文件处理和算量计算的 REST API 接口",
    version="3.0.0"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 临时文件目录
TEMP_DIR = Path(tempfile.gettempdir()) / "hydraulic_cad"
TEMP_DIR.mkdir(exist_ok=True)

# 输出目录
OUTPUT_DIR = Path("C:/Outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


# ==================== 数据模型 ====================
class FileInfo(BaseModel):
    name: str
    path: str
    size: int


class TaskParams(BaseModel):
    # 通用参数
    files: List[FileInfo] = []
    outputDir: str = "C:/Outputs"
    outputName: str = "output"
    
    # 断面合并参数
    layerA: Optional[str] = None
    layerB: Optional[str] = None
    outputLayer: Optional[str] = None
    
    # 批量粘贴参数
    srcX0: Optional[str] = None
    srcY0: Optional[str] = None
    srcBX: Optional[str] = None
    srcBY: Optional[str] = None
    spacing: Optional[str] = None
    dstY: Optional[str] = None
    dstBY: Optional[str] = None
    sourceFile: Optional[Dict] = None
    targetFile: Optional[Dict] = None
    
    # 快速填充参数
    layer: Optional[str] = None
    textHeight: Optional[str] = None
    
    # 分类算量参数
    stationLayer: Optional[str] = None
    mergeSection: Optional[bool] = True
    
    # 分层算量参数
    elevation: Optional[str] = None


class TaskResult(BaseModel):
    success: bool
    results: List[Dict] = []
    error: Optional[str] = None
    logs: List[str] = []


# ==================== 日志记录 ====================
class Logger:
    """日志记录器"""
    
    def __init__(self):
        self.logs = []
        
    def log(self, message: str, level: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {"info": "ℹ️", "success": "✅", "error": "❌", "warning": "⚠️"}.get(level, "ℹ️")
        entry = f"[{timestamp}] {prefix} {message}"
        self.logs.append(entry)
        print(entry)
        
    def clear(self):
        self.logs.clear()


# ==================== API 路由 ====================
@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "engine": "available" if ENGINE_AVAILABLE else "unavailable",
        "version": "3.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/upload")
async def upload_file(files: List[UploadFile] = File(...)):
    """上传文件"""
    uploaded_files = []
    
    for file in files:
        # 保存到临时目录
        file_path = TEMP_DIR / file.filename
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_info = {
            "name": file.filename,
            "path": str(file_path),
            "size": file_path.stat().st_size
        }
        uploaded_files.append(file_info)
        
    return {"files": uploaded_files}


@app.post("/api/task/autoline")
async def run_autoline(params: TaskParams):
    """执行断面线合并任务"""
    logger = Logger()
    results = []
    
    try:
        logger.log("开始执行断面线合并任务...")
        
        if not ENGINE_AVAILABLE:
            return {"success": False, "error": "引擎模块不可用", "logs": logger.logs}
        
        for file_info in params.files:
            input_path = file_info.get("path", "")
            if not os.path.exists(input_path):
                logger.log(f"文件不存在: {input_path}", "error")
                continue
                
            logger.log(f"处理文件: {file_info.get('name', '未知')}")
            
            # 构建参数
            task_params = {
                'files': [input_path],
                '图层A名称': params.layerA or '断面线 1',
                '图层B名称': params.layerB or '断面线 2',
            }
            
            # 执行任务
            def log_func(msg):
                logger.log(msg)
                
            engine_cad.run_autoline(task_params, log_func)
            
            # 检查输出文件
            base_name = os.path.splitext(input_path)[0]
            output_file = base_name + "_bottom_merged.dxf"
            
            if os.path.exists(output_file):
                results.append({
                    "name": os.path.basename(output_file),
                    "path": output_file,
                    "url": f"/api/download?file={output_file}"
                })
                logger.log(f"生成输出文件: {output_file}", "success")
            
        return {"success": True, "results": results, "logs": logger.logs}
        
    except Exception as e:
        logger.log(f"任务执行异常: {str(e)}", "error")
        logger.log(traceback.format_exc(), "error")
        return {"success": False, "error": str(e), "logs": logger.logs}


@app.post("/api/task/autopaste")
async def run_autopaste(params: TaskParams):
    """执行批量粘贴任务"""
    logger = Logger()
    results = []
    
    try:
        logger.log("开始执行批量粘贴任务...")
        
        if not ENGINE_AVAILABLE:
            return {"success": False, "error": "引擎模块不可用", "logs": logger.logs}
        
        source_file = params.sourceFile
        target_file = params.targetFile
        
        if not source_file or not target_file:
            return {"success": False, "error": "缺少源文件或目标文件", "logs": logger.logs}
        
        logger.log(f"源文件: {source_file.get('name', '未知')}")
        logger.log(f"目标文件: {target_file.get('name', '未知')}")
        
        # 构建参数
        task_params = {
            '源文件名': source_file.get('path', ''),
            '目标文件名': target_file.get('path', ''),
            '源端0点X': params.srcX0 or '86.8540',
            '源端0点Y': params.srcY0 or '-15.0622',
            '源端基点X': params.srcBX or '86.0030',
            '源端基点Y': params.srcBY or '-35.2980',
            '断面间距': params.spacing or '-148.4760',
            '目标桩号Y': params.dstY or '-1470.5289',
            '目标基点Y': params.dstBY or '-1363.5000',
        }
        
        def log_func(msg):
            logger.log(msg)
            
        engine_cad.run_autopaste(task_params, log_func)
        
        # 检查输出文件
        target_path = target_file.get('path', '')
        base_name = os.path.splitext(target_path)[0]
        output_file = base_name + "_RESULT.dxf"
        
        if os.path.exists(output_file):
            results.append({
                "name": os.path.basename(output_file),
                "path": output_file,
                "url": f"/api/download?file={output_file}"
            })
            logger.log(f"生成输出文件: {output_file}", "success")
        
        return {"success": True, "results": results, "logs": logger.logs}
        
    except Exception as e:
        logger.log(f"任务执行异常: {str(e)}", "error")
        logger.log(traceback.format_exc(), "error")
        return {"success": False, "error": str(e), "logs": logger.logs}


@app.post("/api/task/autohatch")
async def run_autohatch(params: TaskParams):
    """执行快速填充任务"""
    logger = Logger()
    results = []
    
    try:
        logger.log("开始执行快速填充任务...")
        
        if not ENGINE_AVAILABLE:
            return {"success": False, "error": "引擎模块不可用", "logs": logger.logs}
        
        for file_info in params.files:
            input_path = file_info.get("path", "")
            if not os.path.exists(input_path):
                logger.log(f"文件不存在: {input_path}", "error")
                continue
                
            logger.log(f"处理文件: {file_info.get('name', '未知')}")
            
            # 构建参数
            task_params = {
                'files': [input_path],
                '填充层名称': params.layer or 'AA_填充算量层',
            }
            
            # 执行任务
            def log_func(msg):
                logger.log(msg)
                
            engine_cad.run_autohatch(task_params, log_func)
            
            # 检查输出文件
            base_name = os.path.splitext(input_path)[0]
            
            for suffix in ['_填充完成.dxf', '_面积明细表.xlsx']:
                output_file = base_name + suffix
                if os.path.exists(output_file):
                    results.append({
                        "name": os.path.basename(output_file),
                        "path": output_file,
                        "url": f"/api/download?file={output_file}"
                    })
                    logger.log(f"生成输出文件: {output_file}", "success")
            
        return {"success": True, "results": results, "logs": logger.logs}
        
    except Exception as e:
        logger.log(f"任务执行异常: {str(e)}", "error")
        logger.log(traceback.format_exc(), "error")
        return {"success": False, "error": str(e), "logs": logger.logs}


@app.post("/api/task/autoclassify")
async def run_autoclassify(params: TaskParams):
    """执行分类算量任务"""
    logger = Logger()
    results = []
    
    try:
        logger.log("开始执行分类算量任务...")
        
        if not ENGINE_AVAILABLE:
            return {"success": False, "error": "引擎模块不可用", "logs": logger.logs}
        
        for file_info in params.files:
            input_path = file_info.get("path", "")
            if not os.path.exists(input_path):
                logger.log(f"文件不存在: {input_path}", "error")
                continue
                
            logger.log(f"处理文件: {file_info.get('name', '未知')}")
            
            # 构建参数
            layer_a = params.layerA or 'DMX'
            layer_b = params.layerB or ''
            layer_str = f"{layer_a},{layer_b}" if layer_b else layer_a
            
            task_params = {
                'files': [input_path],
                '断面线图层': layer_str,
                '桩号图层': params.stationLayer or '0-桩号',
                '合并断面线': params.mergeSection if params.mergeSection is not None else True,
            }
            
            # 执行任务
            def log_func(msg):
                logger.log(msg)
                
            engine_cad.run_autoclassify(task_params, log_func)
            
            # 检查输出文件
            base_name = os.path.splitext(input_path)[0]
            
            for suffix in ['_算量汇总.xlsx', '_分类汇总.xlsx']:
                output_file = base_name + suffix
                if os.path.exists(output_file):
                    results.append({
                        "name": os.path.basename(output_file),
                        "path": output_file,
                        "url": f"/api/download?file={output_file}"
                    })
                    logger.log(f"生成输出文件: {output_file}", "success")
            
        return {"success": True, "results": results, "logs": logger.logs}
        
    except Exception as e:
        logger.log(f"任务执行异常: {str(e)}", "error")
        logger.log(traceback.format_exc(), "error")
        return {"success": False, "error": str(e), "logs": logger.logs}


@app.post("/api/task/autocut")
async def run_autocut(params: TaskParams):
    """执行分层算量任务"""
    logger = Logger()
    results = []
    
    try:
        logger.log("开始执行分层算量任务...")
        
        if not ENGINE_AVAILABLE:
            return {"success": False, "error": "引擎模块不可用", "logs": logger.logs}
        
        for file_info in params.files:
            input_path = file_info.get("path", "")
            if not os.path.exists(input_path):
                logger.log(f"文件不存在: {input_path}", "error")
                continue
                
            logger.log(f"处理文件: {file_info.get('name', '未知')}")
            
            # 构建参数
            task_params = {
                'files': [input_path],
                '分层线高程': params.elevation or '-5',
            }
            
            # 执行任务
            def log_func(msg):
                logger.log(msg)
                
            engine_cad.run_autocut(task_params, log_func)
            
            # 检查输出文件
            base_name = os.path.splitext(input_path)[0]
            output_file = base_name + "_分层算量.xlsx"
            
            if os.path.exists(output_file):
                results.append({
                    "name": os.path.basename(output_file),
                    "path": output_file,
                    "url": f"/api/download?file={output_file}"
                })
                logger.log(f"生成输出文件: {output_file}", "success")
            
        return {"success": True, "results": results, "logs": logger.logs}
        
    except Exception as e:
        logger.log(f"任务执行异常: {str(e)}", "error")
        logger.log(traceback.format_exc(), "error")
        return {"success": False, "error": str(e), "logs": logger.logs}


@app.get("/api/download")
async def download_file(file: str):
    """下载文件"""
    if not os.path.exists(file):
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return FileResponse(
        path=file,
        filename=os.path.basename(file),
        media_type="application/octet-stream"
    )


# ==================== 主入口 ====================
if __name__ == "__main__":
    import uvicorn
    
    print("=" * 50)
    print("航道断面算量自动化平台 v3.0 - 后端服务")
    print("=" * 50)
    print(f"引擎状态: {'可用' if ENGINE_AVAILABLE else '不可用'}")
    print(f"临时目录: {TEMP_DIR}")
    print(f"输出目录: {OUTPUT_DIR}")
    print("=" * 50)
    
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info"
    )