import os
import sys
from pathlib import Path


def get_base_dir() -> Path:
    """获取程序执行根目录。
    
    - 如果是未打包的开发环境，返回项目的根目录 (backend 的上一级)。
    - 如果是 PyInstaller 打包环境，返回解压后的临时目录 sys._MEIPASS。
    资源文件（如内置的模板图片、前端静态文件）应当放在这里，因为它们会被打包进 .exe 中。
    """
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)  # type: ignore
    # 当前文件在 backend/app/core/paths.py
    # 它的 parent.parent.parent.parent 是项目根目录
    return Path(__file__).resolve().parent.parent.parent.parent


def get_data_dir() -> Path:
    """获取数据持久化根目录。
    
    - 如果是未打包的开发环境，返回项目的根目录下的 backend/data。
    - 如果是 PyInstaller 打包环境，返回 .exe 文件所在的同级目录下的 data 文件夹。
    运行产生的数据（如 demo.db、audit.jsonl、截图留痕、缓存等）绝对不能放在 sys._MEIPASS，
    否则程序一关闭就会被操作系统清理掉。
    """
    if getattr(sys, 'frozen', False):
        data_dir = Path(sys.executable).parent / "data"
    else:
        data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    
    # 确保目录存在
    os.makedirs(data_dir, exist_ok=True)
    return data_dir
