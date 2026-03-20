import express from "express";
import { createServer as createViteServer } from "vite";
import path from "path";
import { fileURLToPath } from "url";
import multer from "multer";
import fs from "fs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function startServer() {
  const app = express();
  const PORT = 3000;

  // Configure multer for file uploads
  const upload = multer({ dest: "uploads/" });

  // API routes
  app.get("/api/health", (req, res) => {
    res.json({ status: "ok" });
  });

  app.post("/api/upload", upload.array("files"), (req, res) => {
    const files = req.files as Express.Multer.File[];
    if (!files || files.length === 0) {
      return res.status(400).json({ error: "No files uploaded" });
    }
    
    // Return file info
    const fileInfo = files.map(f => ({
      name: f.originalname,
      path: f.path,
      size: f.size
    }));
    
    res.json({ files: fileInfo });
  });

  app.post("/api/task/:type", express.json(), (req, res) => {
    const taskType = req.params.type;
    const params = req.body;
    
    console.log(`Executing task: ${taskType}`, params);
    
    // Mock task execution
    // In a real scenario, this would call the CAD engine
    setTimeout(() => {
      res.json({
        success: true,
        message: `Task ${taskType} executed successfully (Mock)`,
        results: [
          { name: "result.dxf", url: "/downloads/mock-result.dxf" },
          { name: "report.xlsx", url: "/downloads/mock-report.xlsx" }
        ]
      });
    }, 2000);
  });

  // Serve static files from uploads/ and downloads/ if needed
  app.use("/downloads", express.static(path.join(__dirname, "downloads")));

  // Vite middleware for development
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
