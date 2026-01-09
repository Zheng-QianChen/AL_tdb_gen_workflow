from fastapi import APIRouter, Request, UploadFile, HTTPException, status
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from pathlib import Path
import os, json, uuid, shutil, fastapi, asyncio
from config import logger, ALLOWED_BASE_DIR, UPLOAD_DIR, RUN_DIR, BASE_DATA_DIR

file_router = APIRouter()

# 定义请求模型
class FilePathRequest(BaseModel):
    file_path: str

def is_safe_path(base_dir: str, file_path: str) -> bool:
    """
    检查文件路径是否在允许的基础目录内，防止路径遍历攻击
    """
    base_path = Path(base_dir).resolve()
    resolved_file_path = Path(file_path).resolve()
    
    # 确保文件路径是基础目录的子目录
    return base_path in resolved_file_path.parents or base_path == resolved_file_path

@file_router.post("/save_input_json", summary="api.summary_save_json")
async def save_input_json(request: Request):
    """将配置保存到 input.json 文件"""
    try:
        logger.info("recieve the save input.json request")
        
        # 解析请求数据
        try:
            config_data = await request.json()
            raw_filename = config_data.get("filename", "input.json")
            filename = os.path.basename(raw_filename)  # 防止路径注入
            data_len = len(json.dumps(config_data.get("data")))
            logger.info(f"recieve the file name: {filename}")
            logger.info(f"recieve the save request: {data_len} words")
        except Exception as e:
            logger.error(f"parsing JSON fails: {str(e)}")
            return JSONResponse(
                status_code=400,
                content={"success": False, "message_key": "api.err_json_parse"} # 使用 Key
            )
        
        # 保存文件
        try:
            save_path = Path(RUN_DIR)
            save_path.mkdir(parents=True, exist_ok=True) # 确保父目录也一并创建
            file_path = save_path / filename
            counter = 0
            if file_path.exists():
                counter = 0
                backup_file = file_path
                # 寻找可用的备份文件名
                while backup_file.exists():
                    name, ext = os.path.splitext(filename)
                    backup_file = save_path / f"{name}_{counter}{ext}"
                    counter += 1
                # 安全地备份旧文件
                os.rename(file_path, backup_file)
                logger.info(f"backup the older input.json to: {backup_file}")
            with open(save_path/filename, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"success save in: {save_path.absolute()}")
            return {
                "success": True,
                "message_key": "api.save_success", # 使用 Key
                "file_path": str(file_path.absolute())
            }
        except PermissionError:
            logger.error(f"Permission error: {save_path.absolute()}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message_key": "api.err_permission"}
            )
            
    except Exception as e:
        logger.error(f"Error in save file: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message_key": "api.err_server", "detail": str(e)}
        )

@file_router.post("/upload_file")
async def upload_file(file: UploadFile = fastapi.File(...)):
    """上传文件并复制到程序目录下的uploads文件夹"""
    try:
        # 创建目标文件路径
        filename = file.filename

        # 创建目标文件路径
        if not filename:  # 处理没有文件名的情况
            filename = f"unknown_file_{uuid.uuid4().hex[:8]}"
        
        # 处理重名文件
        file_path = UPLOAD_DIR / filename
        counter = 1
        while file_path.exists():
            name, ext = os.path.splitext(filename)
            name = f"{name}_{counter}{ext}"
            file_path = UPLOAD_DIR / name
            counter += 1
        
        # 保存文件
        with open(file_path, "wb") as buffer:
            # 分块读取写入，处理大文件更高效
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                buffer.write(chunk)
        
        logger.info(f"file is copy to: {file_path.resolve()}")
        
        # 返回文件在服务器上的路径
        return {
            "success": True,
            "filename": name,
            "file_path": str(file_path.resolve()),  # 返回绝对路径
            "relative_path": f"uploads/{name}",  # 用于前端访问的相对路径
            "url": f"/uploads/{name}"  # 可直接访问的URL
        }
    except Exception as e:
        logger.error(f"upload fail: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"upload fail: {str(e)}"}
        )
    finally:
        await file.close()

@file_router.post("/read-record", summary="reaing file content")
async def read_record(request: FilePathRequest):
    try:
        file_path = request.file_path
        logger.info(f"try to read file: {file_path}")
        
        # 安全检查
        if not is_safe_path(ALLOWED_BASE_DIR, file_path):
            logger.warning(f"file path is unsafe: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="permission denied for this file path"
            )
        
        # 检查文件是否存在
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logger.warning(f"file is unexits: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="file is unexits"
            )
            
        # 检查是否是文件
        if not file_path_obj.is_file():
            logger.warning(f"Error: Not a file: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Error: Not a file"
            )
        
        # 检查文件大小，防止过大文件
        file_size = file_path_obj.stat().st_size
        max_size = 10 * 1024 * 1024  # 10MB
        if file_size > max_size:
            error_msg = f"Error: too long: {file_path} (Now: {file_size} bytes, Maxium: {max_size} bytes)"
            logger.warning(error_msg)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=error_msg
            )
        
        # 异步读取文件内容
        try:
            # 使用异步方式读取文件
            async def read_file_async(path: Path) -> str:
                loop = asyncio.get_event_loop()
                # 在线程池中执行文件读取，避免阻塞事件循环
                return await loop.run_in_executor(
                    None, 
                    path.read_text, 
                    'utf-8'
                )
            
            content = await read_file_async(file_path_obj)
            
            logger.info(f"Read success: {file_path} ({len(content)} bytes)")

            return JSONResponse({
                "success": True,
                "content": content
            })
            
        except Exception as e:
            logger.error(f"fails in reading: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"fails in reading: {str(e)}"
            )
            
    except HTTPException:
        # 重新抛出已定义的HTTP异常
        raise
    except Exception as e:
        logger.error(f"responce has some problem: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server has some problem: {str(e)}"
        )
    
@file_router.get("/get_data_file/{folder}/{filename}")
async def get_data_file(folder: str, filename: str):
    # 安全检查，防止路径穿越
    safe_filename = os.path.basename(filename)
    file_path = Path(BASE_DATA_DIR) / folder / safe_filename
    
    if file_path.exists():
        return FileResponse(file_path)
    return JSONResponse(status_code=404, content={"message": "File not found"})

@file_router.get("/get_config_status")
async def get_config_status(filename: str):
    try:
        # 防止目录遍历攻击
        safe_filename = os.path.basename(filename)
        target_path = Path(RUN_DIR) / safe_filename
        print(f"DEBUG: 正在尝试访问的绝对路径是: {target_path.absolute()}")
        print(f"DEBUG: 该路径是否存在: {target_path.exists()}")
        if not target_path.exists():
            return JSONResponse(status_code=404, content={"success": False, "detail": "File not found"})

        with open(target_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            
        return config_data # 直接返回配置内容
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "detail": str(e)})
    