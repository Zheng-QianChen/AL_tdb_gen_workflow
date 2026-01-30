import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=1)

# 安全配置
ALLOWED_BASE_DIR = ""  # 请根据实际情况修改
# 路径配置
# 其他html文件的路径
STATIC_DIR = Path("./static")
# 上传文件的路径
UPLOAD_DIR = Path("./data/uploads")
# input.json 的路径
RUN_DIR = Path("./data/run")
# 相分析的路径
WORKING_DIR = Path("./data/Phase_data")
BASE_DATA_DIR = Path("./data")