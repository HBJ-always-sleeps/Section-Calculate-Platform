import React, { useState, useRef, useEffect } from "react";
import { 
  Link2, 
  Clipboard, 
  PaintBucket, 
  Ruler, 
  Layers, 
  Upload, 
  Trash2, 
  Play, 
  Download, 
  FileText, 
  CheckCircle, 
  AlertCircle,
  Settings,
  X,
  Monitor,
  Database,
  Terminal,
  Info,
  Folder
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

type TaskType = "autoline" | "autopaste" | "autohatch" | "autoclassify" | "autocut";

interface FileInfo {
  name: string;
  path: string;
  size: number;
}

interface TaskResult {
  name: string;
  url: string;
  path?: string;
}

export default function App() {
  const [showSplash, setShowSplash] = useState(true);
  const [activeTab, setActiveTab] = useState<TaskType>("autoline");
  const [selectedFile, setSelectedFile] = useState<FileInfo | null>(null);
  const [sourceFile, setSourceFile] = useState<FileInfo | null>(null);
  const [targetFile, setTargetFile] = useState<FileInfo | null>(null);
  const [uploading, setUploading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [results, setResults] = useState<TaskResult[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [backendStatus, setBackendStatus] = useState<"online" | "offline" | "checking">("checking");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sourceInputRef = useRef<HTMLInputElement>(null);
  const targetInputRef = useRef<HTMLInputElement>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  // 表单状态
  const [autolineParams, setAutolineParams] = useState({ layerA: "断面线 1", layerB: "断面线 2", outputLayer: "合并断面线", outputDir: "C:/Outputs", outputName: "断面合并结果" });
  const [autopasteParams, setAutopasteParams] = useState({ srcX0: "86.8540", srcY0: "-15.0622", srcBX: "86.0030", srcBY: "-35.2980", spacing: "-148.4760", dstY: "-1470.5289", dstBY: "-1363.5000", outputDir: "C:/Outputs", outputName: "批量粘贴结果" });
  const [autohatchParams, setAutohatchParams] = useState({ layer: "AA_填充算量层", textHeight: "3.0", outputDir: "C:/Outputs", outputName: "快速填充结果" });
  const [autoclassifyParams, setAutoclassifyParams] = useState({ layerA: "DMX", layerB: "断面线", stationLayer: "0-桩号", mergeSection: true, outputDir: "C:/Outputs", outputName: "分类算量结果" });
  const [autocutParams, setAutocutParams] = useState({ elevation: "-5", outputDir: "C:/Outputs", outputName: "分层算量结果" });

  // 启动时检测后端状态 (仅一次)
  useEffect(() => {
    checkBackend();
    
    // 3秒后关闭启动页
    const timer = setTimeout(() => {
      setShowSplash(false);
    }, 3000);
    
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  const checkBackend = async () => {
    try {
      const res = await fetch("/api/health");
      if (res.ok) setBackendStatus("online");
      else setBackendStatus("offline");
    } catch {
      setBackendStatus("offline");
    }
  };

  const addLog = (msg: string, type: "info" | "error" | "success" = "info") => {
    const prefix = type === "error" ? "❌ " : type === "success" ? "✅ " : "ℹ️ ";
    setLogs(prev => [...prev, `${prefix}[${new Date().toLocaleTimeString()}] ${msg}`]);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>, target: "single" | "source" | "target") => {
    const selectedFiles = e.target.files;
    if (!selectedFiles || selectedFiles.length === 0) return;

    setUploading(true);
    addLog(`正在上传文件: ${selectedFiles[0].name}...`);

    const formData = new FormData();
    formData.append("files", selectedFiles[0]);

    try {
      const response = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      if (data.files && data.files.length > 0) {
        const file = data.files[0];
        if (target === "single") setSelectedFile(file);
        else if (target === "source") setSourceFile(file);
        else if (target === "target") setTargetFile(file);
        addLog(`文件 ${file.name} 上传成功`, "success");
      }
    } catch (error) {
      addLog(`上传失败: ${error}`, "error");
    } finally {
      setUploading(false);
    }
  };

  const clearFiles = () => {
    setSelectedFile(null);
    setSourceFile(null);
    setTargetFile(null);
    addLog("已清除选择的文件");
  };

  const runTask = async () => {
    const isAutoPaste = activeTab === "autopaste";
    if (isAutoPaste) {
      if (!sourceFile || !targetFile) {
        addLog("错误: 请选择源文件和目标文件", "error");
        return;
      }
    } else {
      if (!selectedFile) {
        addLog("错误: 请先选择 DXF 文件", "error");
        return;
      }
    }

    setExecuting(true);
    setResults([]);
    addLog(`正在启动任务: ${tabs.find(t => t.id === activeTab)?.label}...`);

    let params = {};
    switch (activeTab) {
      case "autoline": params = autolineParams; break;
      case "autopaste": params = autopasteParams; break;
      case "autohatch": params = autohatchParams; break;
      case "autoclassify": params = autoclassifyParams; break;
      case "autocut": params = autocutParams; break;
    }

    const taskFiles = isAutoPaste ? [sourceFile, targetFile] : [selectedFile];

    try {
      const response = await fetch(`/api/task/${activeTab}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...params, files: taskFiles }),
      });
      const data = await response.json();
      if (data.success) {
        setResults(data.results);
        addLog(`任务 ${tabs.find(t => t.id === activeTab)?.label} 执行成功`, "success");
      } else {
        addLog(`任务执行失败: ${data.error}`, "error");
      }
    } catch (error) {
      addLog(`任务执行异常: ${error}`, "error");
    } finally {
      setExecuting(false);
    }
  };

  const tabs = [
    { id: "autoline", label: "断面合并", icon: <Link2 size={18} /> },
    { id: "autopaste", label: "批量粘贴", icon: <Clipboard size={18} /> },
    { id: "autohatch", label: "快速填充", icon: <PaintBucket size={18} /> },
    { id: "autoclassify", label: "分类算量", icon: <Ruler size={18} /> },
    { id: "autocut", label: "分层算量", icon: <Layers size={18} /> },
  ];

  return (
    <div className="min-h-screen bg-[#0F0F0F] text-[#E4E3E0] font-sans selection:bg-[#E4E3E0] selection:text-[#0F0F0F] flex items-center justify-center p-4">
      {/* 启动页 (Splash Screen) */}
      <AnimatePresence>
        {showSplash && (
          <motion.div 
            initial={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[100] bg-[#0F0F0F] flex flex-col items-center justify-center"
          >
            <motion.div
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: 0.5 }}
              className="relative"
            >
              <img src="/input_file_0.png" alt="Logo" className="w-64 h-64 shadow-2xl rounded-3xl" />
              <motion.div 
                className="absolute -bottom-12 left-0 right-0 text-center"
                initial={{ y: 20, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: 0.3 }}
              >
                <h2 className="text-3xl font-bold tracking-[0.2em] font-serif italic">航道断面算量自动化平台</h2>
                <p className="text-xs font-mono opacity-30 mt-2 uppercase tracking-[0.5em]">Waterway Section Automation Platform</p>
              </motion.div>
            </motion.div>
            <div className="mt-24 w-48 h-1 bg-[#2A2A2A] rounded-full overflow-hidden">
              <motion.div 
                className="h-full bg-[#E4E3E0]"
                initial={{ width: 0 }}
                animate={{ width: "100%" }}
                transition={{ duration: 2.5, ease: "easeInOut" }}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 主界面容器 - 限制最大宽度和高度，模拟桌面软件 */}
      <div className="w-full max-w-[1280px] h-[800px] bg-[#141414] border border-[#2A2A2A] rounded-2xl shadow-[0_0_50px_rgba(0,0,0,0.5)] overflow-hidden flex flex-col">
        
        {/* 顶部导航栏 */}
        <header className="border-b border-[#2A2A2A] bg-[#1A1A1A] px-6 py-3 flex justify-between items-center shrink-0">
          <div className="flex items-center gap-4">
            <img src="/input_file_0.png" alt="Icon" className="w-12 h-12 rounded-lg shadow-lg" />
            <div>
              <h1 className="text-2xl font-bold tracking-tight italic font-serif">航道断面算量自动化平台 <span className="text-sm font-mono not-italic opacity-50 ml-2">v3.1</span></h1>
              <div className="flex items-center gap-2 mt-0.5">
                <div className={`w-2 h-2 rounded-full ${backendStatus === "online" ? "bg-green-500" : backendStatus === "offline" ? "bg-red-500" : "bg-yellow-500 animate-pulse"}`} />
                <span className="text-xs font-mono uppercase opacity-40 tracking-widest">
                  后端状态: {backendStatus === "online" ? "已就绪" : backendStatus === "offline" ? "未连接" : "检测中..."}
                </span>
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <button className="p-2 bg-[#242424] border border-[#333] rounded-lg hover:bg-[#2A2A2A] transition-colors">
              <Database size={16} />
            </button>
            <button className="p-2 bg-[#242424] border border-[#333] rounded-lg hover:bg-[#2A2A2A] transition-colors">
              <Settings size={16} />
            </button>
          </div>
        </header>

        {/* 主体内容区 - 左右布局 */}
        <div className="flex-1 flex overflow-hidden">
          
          {/* 左侧: 参数配置与文件管理 (60%) */}
          <div className="w-[60%] border-r border-[#2A2A2A] flex flex-col overflow-hidden">
            
            {/* 标签页选择 */}
            <div className="flex bg-[#1A1A1A] border-b border-[#2A2A2A]">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as TaskType)}
                  className={`flex-1 flex items-center justify-center gap-2 py-4 text-base font-medium transition-all relative ${
                    activeTab === tab.id ? "text-[#E4E3E0] bg-[#141414]" : "text-[#707070] hover:text-[#E4E3E0] hover:bg-[#141414]/50"
                  }`}
                >
                  {tab.icon}
                  {tab.label}
                  {activeTab === tab.id && (
                    <motion.div 
                      layoutId="activeTab" 
                      className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#E4E3E0]" 
                    />
                  )}
                </button>
              ))}
            </div>

            {/* 左侧内容滚动区 */}
            <div className="flex-1 overflow-y-auto p-6 space-y-8 custom-scrollbar">
              {/* 文件列表 */}
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <div className="flex items-center gap-2 opacity-30">
                    <FileText size={14} />
                    <span className="text-xs uppercase tracking-widest font-mono">文件选择</span>
                  </div>
                  <button 
                    onClick={clearFiles}
                    className="px-3 py-1.5 border border-[#333] rounded text-xs font-bold hover:bg-[#2A2A2A] transition-all"
                  >
                    重置选择
                  </button>
                </div>
                
                <div className="space-y-3">
                  {activeTab === "autopaste" ? (
                    <>
                      <FileRow 
                        label="源文件" 
                        file={sourceFile} 
                        onSelect={() => sourceInputRef.current?.click()} 
                        onClear={() => setSourceFile(null)} 
                      />
                      <FileRow 
                        label="目标文件" 
                        file={targetFile} 
                        onSelect={() => targetInputRef.current?.click()} 
                        onClear={() => setTargetFile(null)} 
                      />
                      <input type="file" accept=".dxf" className="hidden" ref={sourceInputRef} onChange={(e) => handleFileUpload(e, "source")} />
                      <input type="file" accept=".dxf" className="hidden" ref={targetInputRef} onChange={(e) => handleFileUpload(e, "target")} />
                    </>
                  ) : (
                    <>
                      <FileRow 
                        label="待处理 DXF" 
                        file={selectedFile} 
                        onSelect={() => fileInputRef.current?.click()} 
                        onClear={() => setSelectedFile(null)} 
                      />
                      <input type="file" accept=".dxf" className="hidden" ref={fileInputRef} onChange={(e) => handleFileUpload(e, "single")} />
                    </>
                  )}
                </div>
              </div>

              {/* 参数配置 */}
              <div className="space-y-6">
                <div className="flex items-center gap-2 opacity-30">
                  <Info size={14} />
                  <span className="text-xs uppercase tracking-widest font-mono">参数设置 / {tabs.find(t => t.id === activeTab)?.label}</span>
                </div>
                
                <AnimatePresence mode="wait">
                  <motion.div
                    key={activeTab}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    transition={{ duration: 0.2 }}
                    className="grid grid-cols-2 gap-6"
                  >
                    {activeTab === "autoline" && (
                      <>
                        <ParamInput label="图层 A 名称" value={autolineParams.layerA} onChange={(v) => setAutolineParams({...autolineParams, layerA: v})} />
                        <ParamInput label="图层 B 名称" value={autolineParams.layerB} onChange={(v) => setAutolineParams({...autolineParams, layerB: v})} />
                        <ParamInput label="输出图层名" value={autolineParams.outputLayer} onChange={(v) => setAutolineParams({...autolineParams, outputLayer: v})} fullWidth />
                        <div className="col-span-2 grid grid-cols-2 gap-6 pt-4 border-t border-[#2A2A2A]">
                          <ParamInput label="输出目录" value={autolineParams.outputDir} onChange={(v) => setAutolineParams({...autolineParams, outputDir: v})} isPath />
                          <ParamInput label="输出文件名" value={autolineParams.outputName} onChange={(v) => setAutolineParams({...autolineParams, outputName: v})} />
                        </div>
                      </>
                    )}

                    {activeTab === "autopaste" && (
                      <>
                        <ParamInput label="源端 0 点 X" value={autopasteParams.srcX0} onChange={(v) => setAutopasteParams({...autopasteParams, srcX0: v})} />
                        <ParamInput label="源端 0 点 Y" value={autopasteParams.srcY0} onChange={(v) => setAutopasteParams({...autopasteParams, srcY0: v})} />
                        <ParamInput label="源端基点 X" value={autopasteParams.srcBX} onChange={(v) => setAutopasteParams({...autopasteParams, srcBX: v})} />
                        <ParamInput label="源端基点 Y" value={autopasteParams.srcBY} onChange={(v) => setAutopasteParams({...autopasteParams, srcBY: v})} />
                        <ParamInput label="断面间距" value={autopasteParams.spacing} onChange={(v) => setAutopasteParams({...autopasteParams, spacing: v})} />
                        <ParamInput label="目标桩号 Y" value={autopasteParams.dstY} onChange={(v) => setAutopasteParams({...autopasteParams, dstY: v})} />
                        <ParamInput label="目标基点 Y" value={autopasteParams.dstBY} onChange={(v) => setAutopasteParams({...autopasteParams, dstBY: v})} fullWidth />
                        <div className="col-span-2 grid grid-cols-2 gap-6 pt-4 border-t border-[#2A2A2A]">
                          <ParamInput label="输出目录" value={autopasteParams.outputDir} onChange={(v) => setAutopasteParams({...autopasteParams, outputDir: v})} isPath />
                          <ParamInput label="输出文件名" value={autopasteParams.outputName} onChange={(v) => setAutopasteParams({...autopasteParams, outputName: v})} />
                        </div>
                      </>
                    )}

                    {activeTab === "autohatch" && (
                      <>
                        <ParamInput label="填充层名称" value={autohatchParams.layer} onChange={(v) => setAutohatchParams({...autohatchParams, layer: v})} />
                        <ParamInput label="标注字高" value={autohatchParams.textHeight} onChange={(v) => setAutohatchParams({...autohatchParams, textHeight: v})} />
                        <div className="col-span-2 grid grid-cols-2 gap-6 pt-4 border-t border-[#2A2A2A]">
                          <ParamInput label="输出目录" value={autohatchParams.outputDir} onChange={(v) => setAutohatchParams({...autohatchParams, outputDir: v})} isPath />
                          <ParamInput label="输出文件名" value={autohatchParams.outputName} onChange={(v) => setAutohatchParams({...autohatchParams, outputName: v})} />
                        </div>
                      </>
                    )}

                    {activeTab === "autoclassify" && (
                      <>
                        <ParamInput label="断面线图层 1" value={autoclassifyParams.layerA} onChange={(v) => setAutoclassifyParams({...autoclassifyParams, layerA: v})} />
                        {autoclassifyParams.mergeSection ? (
                          <ParamInput label="断面线图层 2" value={autoclassifyParams.layerB} onChange={(v) => setAutoclassifyParams({...autoclassifyParams, layerB: v})} />
                        ) : (
                          <div className="invisible" /> // 占位符防止布局跳动
                        )}
                        <ParamInput label="桩号图层" value={autoclassifyParams.stationLayer} onChange={(v) => setAutoclassifyParams({...autoclassifyParams, stationLayer: v})} />
                        <div className="flex items-center gap-3 p-3 bg-[#1A1A1A] rounded-lg border border-[#2A2A2A]">
                          <input 
                            type="checkbox" 
                            id="mergeSection"
                            checked={autoclassifyParams.mergeSection}
                            onChange={(e) => setAutoclassifyParams({...autoclassifyParams, mergeSection: e.target.checked})}
                            className="w-5 h-5 rounded border-[#333] bg-[#0F0F0F] text-[#E4E3E0] cursor-pointer"
                          />
                          <label htmlFor="mergeSection" className="text-sm font-medium cursor-pointer">合并断面线</label>
                        </div>
                        <div className="col-span-2 grid grid-cols-2 gap-6 pt-4 border-t border-[#2A2A2A]">
                          <ParamInput label="输出目录" value={autoclassifyParams.outputDir} onChange={(v) => setAutoclassifyParams({...autoclassifyParams, outputDir: v})} isPath />
                          <ParamInput label="输出文件名" value={autoclassifyParams.outputName} onChange={(v) => setAutoclassifyParams({...autoclassifyParams, outputName: v})} />
                        </div>
                      </>
                    )}

                    {activeTab === "autocut" && (
                      <>
                        <ParamInput label="分层线高程 (m)" value={autocutParams.elevation} onChange={(v) => setAutocutParams({...autocutParams, elevation: v})} fullWidth />
                        <div className="col-span-2 grid grid-cols-2 gap-6 pt-4 border-t border-[#2A2A2A]">
                          <ParamInput label="输出目录" value={autocutParams.outputDir} onChange={(v) => setAutocutParams({...autocutParams, outputDir: v})} isPath />
                          <ParamInput label="输出文件名" value={autocutParams.outputName} onChange={(v) => setAutocutParams({...autocutParams, outputName: v})} />
                        </div>
                      </>
                    )}
                  </motion.div>
                </AnimatePresence>
              </div>
            </div>

            {/* 底部执行按钮 */}
            <div className="p-6 border-t border-[#2A2A2A] bg-[#1A1A1A]/50">
              <button 
                onClick={runTask}
                disabled={executing || (activeTab === "autopaste" ? (!sourceFile || !targetFile) : !selectedFile) || backendStatus !== "online"}
                className={`w-full py-4 rounded-xl font-bold text-xl flex items-center justify-center gap-3 transition-all ${
                  executing || (activeTab === "autopaste" ? (!sourceFile || !targetFile) : !selectedFile) || backendStatus !== "online"
                    ? "bg-[#2A2A2A] text-[#555] cursor-not-allowed" 
                    : "bg-[#E4E3E0] text-[#0F0F0F] hover:shadow-[0_0_20px_rgba(228,227,224,0.1)] active:scale-[0.98]"
                }`}
              >
                {executing ? (
                  <>
                    <div className="w-5 h-5 border-2 border-[#0F0F0F] border-t-transparent rounded-full animate-spin" />
                    计算中...
                  </>
                ) : (
                  <>
                    <Play size={20} fill="currentColor" />
                    执行任务
                  </>
                )}
              </button>
            </div>
          </div>

          {/* 右侧: 日志与结果 (40%) */}
          <div className="w-[40%] flex flex-col overflow-hidden bg-[#0D0D0D]">
            
            {/* 成果文件 */}
            <div className="h-[40%] flex flex-col border-b border-[#2A2A2A]">
              <div className="p-4 bg-[#1A1A1A] border-b border-[#2A2A2A] flex items-center gap-2">
                <CheckCircle size={18} className="text-green-500" />
                <span className="text-sm uppercase tracking-widest font-mono opacity-50">成果输出</span>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
                {results.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center opacity-10 italic text-base text-center">
                    <Download size={48} strokeWidth={1} className="mb-2" />
                    等待任务完成
                  </div>
                ) : (
                  results.map((res, i) => (
                    <motion.a 
                      initial={{ opacity: 0, x: 10 }}
                      animate={{ opacity: 1, x: 0 }}
                      key={i} 
                      href={res.url} 
                      download 
                      className="flex items-center justify-between p-4 bg-[#1A1A1A] border border-[#2A2A2A] rounded-lg hover:border-[#E4E3E0] transition-all group"
                    >
                      <div className="flex items-center gap-3 overflow-hidden">
                        {res.name.endsWith(".xlsx") ? <FileText size={20} className="text-green-500 shrink-0" /> : <Layers size={20} className="text-blue-500 shrink-0" />}
                        <div className="flex flex-col truncate">
                          <span className="text-sm font-mono truncate">{res.name}</span>
                          <span className="text-xs font-mono opacity-30 truncate">{res.path || "默认路径"}</span>
                        </div>
                      </div>
                      <Download size={18} className="opacity-20 group-hover:opacity-100" />
                    </motion.a>
                  ))
                )}
              </div>
            </div>

            {/* 运行日志 */}
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="p-4 bg-[#1A1A1A] border-b border-[#2A2A2A] flex justify-between items-center">
                <div className="flex items-center gap-2">
                  <Terminal size={18} className="opacity-50" />
                  <span className="text-sm uppercase tracking-widest font-mono opacity-50">运行控制台</span>
                </div>
                <button onClick={() => setLogs([])} className="text-xs uppercase opacity-20 hover:opacity-100 transition-opacity">清除</button>
              </div>
              <div className="flex-1 overflow-y-auto p-4 font-mono text-sm space-y-1.5 bg-black/40 custom-scrollbar">
                {logs.length === 0 ? (
                  <div className="opacity-10 italic">控制台就绪...</div>
                ) : (
                  logs.map((log, i) => (
                    <div key={i} className="border-l border-[#2A2A2A] pl-3 py-0.5 leading-relaxed opacity-70">
                      {log}
                    </div>
                  ))
                )}
                <div ref={logEndRef} />
              </div>
            </div>
          </div>
        </div>

        {/* 底部状态栏 */}
        <footer className="px-6 py-2 bg-[#1A1A1A] border-t border-[#2A2A2A] flex justify-between items-center shrink-0">
          <div className="flex gap-4 opacity-30 text-xs font-mono uppercase tracking-widest">
            <span>引擎版本: v2.0</span>
            <span>核心算法: DXF-SHAPELY</span>
          </div>
          <div className="opacity-20 text-xs font-mono uppercase tracking-[0.3em]">
            &copy; 2026 航道断面算量自动化平台
          </div>
        </footer>
      </div>

      <style>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: #2A2A2A;
          border-radius: 10px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: #333;
        }
        .no-scrollbar::-webkit-scrollbar {
          display: none;
        }
      `}</style>
    </div>
  );
}

function FileRow({ label, file, onSelect, onClear }: { label: string, file: FileInfo | null, onSelect: () => void, onClear: () => void }) {
  return (
    <div className="flex items-center justify-between p-4 bg-[#1A1A1A] border border-[#2A2A2A] rounded-lg group">
      <div className="flex items-center gap-3 overflow-hidden">
        <div className="text-xs font-mono uppercase opacity-30 w-24 shrink-0">{label}</div>
        {file ? (
          <div className="flex items-center gap-2 truncate">
            <CheckCircle size={16} className="text-green-500 shrink-0" />
            <span className="text-sm font-mono truncate">{file.name}</span>
          </div>
        ) : (
          <span className="text-sm font-mono opacity-20 italic">未选择文件</span>
        )}
      </div>
      <div className="flex gap-2">
        {file ? (
          <button onClick={onClear} className="p-1 text-red-500/40 hover:text-red-500 transition-colors">
            <X size={18} />
          </button>
        ) : (
          <button 
            onClick={onSelect}
            className="px-4 py-2 bg-[#E4E3E0] text-[#0F0F0F] rounded text-sm font-bold hover:bg-white transition-all"
          >
            选择
          </button>
        )}
      </div>
    </div>
  );
}

function ParamInput({ label, value, onChange, fullWidth = false, isPath = false }: { label: string, value: string, onChange: (v: string) => void, fullWidth?: boolean, isPath?: boolean }) {
  const handleBrowse = () => {
    const newPath = prompt("请输入输出目录路径:", value);
    if (newPath !== null) onChange(newPath);
  };

  return (
    <div className={`space-y-2 ${fullWidth ? "col-span-2" : ""}`}>
      <label className="text-xs font-mono uppercase opacity-30 tracking-wider">{label}</label>
      <div className="relative flex items-center">
        <input 
          type="text" 
          value={value} 
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-[#1A1A1A] border border-[#2A2A2A] rounded-lg px-4 py-3 text-base focus:outline-none focus:border-[#E4E3E0] transition-all font-mono pr-12"
        />
        {isPath && (
          <button 
            onClick={handleBrowse}
            className="absolute right-3 p-1 text-[#E4E3E0]/30 hover:text-[#E4E3E0] transition-colors"
            title="浏览目录"
          >
            <Folder size={18} />
          </button>
        )}
      </div>
    </div>
  );
}
