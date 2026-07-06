"""
exe 打包脚本
============
用法: python build_exe.py

生成的可执行文件在 dist/movie_analysis/ 目录下。
"""
import os
import sys
import shutil
import PyInstaller.__main__

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist")

# 收集需要打包的数据文件
datas = [
    ("data/backup_movies.csv", "data"),
    ("config.example.py", "."),
    ("resources/styles/main.qss", "resources/styles"),
]

data_args = []
for src, dst in datas:
    full_src = os.path.join(PROJECT_DIR, src)
    if os.path.exists(full_src):
        data_args.append(f"--add-data={full_src}{os.pathsep}{dst}")
        print(f"  [数据] {src} → {dst}")
    else:
        print(f"  [警告] 文件不存在: {full_src}")

# 隐藏导入（pyecharts 动态导入的模块）
hidden_imports = [
    "--hidden-import=pyecharts",
    "--hidden-import=pyecharts.charts",
    "--hidden-import=pyecharts.options",
    "--hidden-import=pyecharts.render",
    "--hidden-import=pyecharts.faker",
    "--hidden-import=sqlite3",
    "--hidden-import=PIL",
    "--hidden-import=PIL._imaging",
    "--hidden-import=requests",
    "--hidden-import=csv",
    "--hidden-import=json",
    "--hidden-import=re",
    "--hidden-import=threading",
    "--hidden-import=config",
]

args = [
    "main.py",
    "--name=电影票分析系统",
    "--onedir",
    "--windowed",  # 无控制台窗口（GUI 模式）
    "--noconfirm",
    "--clean",
    "--log-level=WARN",
    "--distpath=" + DIST_DIR,
    "--workpath=" + os.path.join(PROJECT_DIR, "build"),
    "--specpath=" + os.path.join(PROJECT_DIR, "build"),
] + data_args + hidden_imports

print("=" * 50)
print("开始打包...")
print("=" * 50)

PyInstaller.__main__.run(args)

print("=" * 50)
print("打包完成!")
print(f"输出目录: {DIST_DIR}")
print("=" * 50)
