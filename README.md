# WeChat RPA Desktop (微信 RPA 自动加微智能体)

本项目是一个跨平台的微信 RPA 自动加微本地 Demo。它通过 **Tauri (v2) + React + TypeScript** 构建桌面端用户界面，并使用 **Rust** 保证应用壳的安全性与稳定性，同时在后台拉起 **FastAPI (Python) + OpenCV + 本地原生 OCR** 引擎，用于执行微信自动化加粉及页面元素的自愈定位。

---

## 📖 项目介绍

在社交营销与私域运营中，微信主动添加好友是一项高频但枯燥的任务。本项目结合了大模型销售智能体的构想，开发了该本地加微客户端。
* **本地化执行**：无需连接云端 OCR 或昂贵的第三方服务，完全依赖系统底层原生 OCR 与 OpenCV 图像识别。
* **安全性与防封**：模拟人工的键盘和鼠标操作（非微信协议 Hook，更不易触发微信风控机制）。
* **自愈定位**：微信界面由于更新、分辨率差异、操作系统不同等会导致界面微小偏差，项目通过 OpenCV 模板匹配与 RapidFuzz 模糊文本相似度计算，实现动态查找输入框与按钮并进行容错定位。

---

## 🛠️ 核心技术栈与依赖库

### 前端 (Desktop GUI)
* **宿主容器**：[Tauri v2](https://tauri.app/) (Rust 构建的跨平台轻量级应用容器)
* **核心框架**：[React 19](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/) + [Vite 6](https://vite.dev/)
* **UI 样式**：Tailwind CSS v4 + Tailwind CSS Animate + Radix UI 组件
* **状态管理**：Zustand
* **异步请求**：TanStack React Query
* **表单校验**：React Hook Form + Zod

### 后端与 RPA 核心 (Python Sidecar)
* **Web 框架**：FastAPI + Uvicorn (通过本地生成的随机 Security Token 鉴权，仅允许本客户端调用)
* **键鼠控制**：PyAutoGUI (模拟手工操作)
* **视觉识别**：OpenCV (`opencv-python`) & Pillow (用于图像匹配与微调定位)
* **本地极速 OCR (纯本地化执行)**：
  * **Windows**：调用 Windows 10/11 本地自带的 WinRT OCR 引擎 (`winrt-Windows.Media.Ocr`)
  * **macOS**：调用 macOS 原生系统级 Vision 框架 (`pyobjc-framework-Vision`)
  * 避免任何三方云端 OCR 接口依赖，速度极快且隐私安全。

---

## 📂 项目目录结构

* 📁 [src/](file:///c:/Users/Administrator/Desktop/aiPS/wechat-rpa-desktop-standalone/src)：前端 React 界面源代码。
  * 📁 `components/`：基础 UI 组件与弹窗。
  * 📁 `hooks/`：自定义 React Hooks（如 API 请求钩子）。
  * 📁 `stores/`：Zustand 全局状态管理。
* 📁 [src-tauri/](file:///c:/Users/Administrator/Desktop/aiPS/wechat-rpa-desktop-standalone/src-tauri)：Tauri 桌面容器部分 (Rust)。
  * 📝 [lib.rs](file:///c:/Users/Administrator/Desktop/aiPS/wechat-rpa-desktop-standalone/src-tauri/src/lib.rs)：应用启动逻辑，负责在后台利用 `uv` 命令异步拉起 FastAPI Python 进程并管理其生命周期。
  * 📝 `tauri.conf.json`：Tauri 配置文件（Sidecar 二进制文件与前端构建配置）。
* 📁 [python/](file:///c:/Users/Administrator/Desktop/aiPS/wechat-rpa-desktop-standalone/python)：Python RPA / 视觉后端。
  * 📁 `backend/app/`：
    * 📝 [main.py](file:///c:/Users/Administrator/Desktop/aiPS/wechat-rpa-desktop-standalone/python/backend/app/main.py)：FastAPI 后端主入口。
    * 📁 `api/`：API 路由，包含 Leads 导入、RPA 任务下发、健康检查与日志审计。
    * 📁 `services/`：RPA 模拟键鼠调度器、OpenCV 模板识别算法与 Windows/macOS 本地 OCR 封装。
  * 📝 `pyproject.toml`：使用 `uv` 统一管理的依赖清单（内置国内 Tsinghua 镜像源加速下载）。

---

## 🚀 本项目安装与启动指南

### 1. 🛠️ 基础环境准备

在开始之前，请确保您的电脑上已经安装了以下开发环境：

1. **Node.js** (推荐 v18 或以上)
2. **pnpm**：项目使用 pnpm 管理前端依赖。
   * 如果未安装，可以使用命令安装：`npm install -g pnpm`
3. **Rust 编译环境**：因为是 Tauri 项目，需要安装 Rust 来编译后端。
   * **Windows 用户**：需要通过 [Rustup](https://rustup.rs/) 安装 Rust，并确保已安装 **Microsoft Visual Studio C++ 生成工具 (MSVC)**。
4. **uv (Python 包与环境管理器)**：
   * 本项目在 Rust 启动时，硬编码了通过 `uv` 命令在后台拉起 Python 后端。因此，您的系统**必须安装 `uv`** 并且将其加入环境变量中。
   * 安装 `uv` 的最简方式：
     * **Windows (PowerShell)**：
       ```powershell
       powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
       ```
     * **macOS/Linux**：
       ```bash
       curl -LsSf https://astral.sh/uv/install.sh | sh
       ```

### 2. 📦 安装依赖

打开终端，进入项目根目录：

* **安装前端依赖**
  ```bash
  pnpm install
  ```

* **安装 Python 依赖**
  在首次运行前，建议进入 `python` 目录让 `uv` 同步并准备好 Python 环境：
  ```bash
  cd python
  uv sync
  ```

### 3. 🏃 启动项目（开发模式）

回到**项目根目录**，执行以下命令：

```bash
pnpm tauri dev
```

### 4. 📦 生产环境打包

如果您需要将应用打包成可分发的安装包，请在项目根目录下运行：

```bash
pnpm tauri build
```

---

## 💻 推荐 IDE 配置

* **编辑器**：[VS Code](https://code.visualstudio.com/)
* **推荐插件**：
  * [Tauri](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode)
  * [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer)
  * [Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python)
