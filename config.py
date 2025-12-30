import logging
from concurrent.futures import ThreadPoolExecutor
from lib.main_process.al_worker import ALRunner
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局实例
runner = ALRunner()  # 单例后台任务

executor = ThreadPoolExecutor(max_workers=1)

# 安全配置
ALLOWED_BASE_DIR = ""  # 请根据实际情况修改

# 路径配置
# 其他html文件的路径
STATIC_DIR = Path("./static")
# 上传文件的路径
UPLOAD_DIR = Path("./uploads")
# input.json 的路径
RUN_DIR = Path("./static/run")
# 相分析的路径
WORKING_DIR = Path("./Phase_data")
    
# # 导出ALRunner类，供其他模块使用
# __all__ = ['runner', 'logger', 'executor', 'ALLOWED_BASE_DIR', 
#            'UPLOAD_DIR', 'STATIC_DIR', 'RUN_DIR', 'ALRunner']
