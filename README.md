# VidMuse

AI 音乐视频生成工具，面向独立音乐人。用户上传歌曲 + 创意描述，系统生成 30-60 秒 MV 粗剪，支持逐镜头修改。

## 技术栈

- **后端**: Python 3.11 + FastAPI + LangGraph 1.0.10
- **前端**: Next.js + TypeScript + Tailwind CSS
- **数据库**: PostgreSQL + Redis
- **存储**: MinIO (S3 兼容)
- **LLM**: DeepSeek / OpenAI 等外部 API

## 项目结构

```
vidMuse/
├── backend/          # FastAPI 后端
├── frontend/         # Next.js 前端
├── config/           # 配置文件
├── prompts/          # Prompt 模板
├── data/             # 本地产物
├── logs/             # 日志文件
├── docs/             # 设计文档
└── scripts/          # 运维脚本
```

## 快速开始

### 后端启动

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 前端启动

```bash
cd frontend
npm install
npm run dev
```

### 配置

1. 复制 `config/base/*.yaml.example` 为 `*.yaml`
2. 修改数据库、Redis、MinIO 配置
3. 配置 LLM API Key

## 开发

详见各模块 README。
