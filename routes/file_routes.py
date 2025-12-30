from fastapi import APIRouter, Request, UploadFile, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path
import os, json, uuid, shutil, fastapi, asyncio
from config import logger, ALLOWED_BASE_DIR, UPLOAD_DIR, RUN_DIR

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

@file_router.post("/save_input_json")
async def save_input_json(request: Request):
    """将配置保存到 input.json 文件"""
    try:
        logger.info("收到保存配置请求")
        
        # 解析请求数据
        try:
            config_data = await request.json()
            logger.info(f"收到配置数据，长度: {len(json.dumps(config_data))} 字符")
        except Exception as e:
            logger.error(f"解析JSON失败: {str(e)}")
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": f"JSON解析错误: {str(e)}"}
            )
        
        # 保存文件
        try:
            save_path = Path(RUN_DIR)
            save_path.mkdir(exist_ok=True)
            filename = "input.json"
            file_path = save_path / filename
            counter = 0
            while file_path.exists():
                name, ext = os.path.splitext(filename)
                name = f"{name}_{counter}{ext}"
                file_path = save_path / name
                counter += 1
            os.rename(save_path/filename, file_path)
            with open(save_path/filename, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            
            os.chmod(save_path, 0o644)
            logger.info(f"成功保存到: {save_path.absolute()}")
            return {
                "success": True,
                "message": "配置已保存",
                "file_path": str(save_path.absolute())
            }
        except PermissionError:
            logger.error(f"没有权限写入文件: {save_path.absolute()}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": f"保存失败：没有权限写入文件"}
            )
        except Exception as e:
            logger.error(f"保存文件失败: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": f"保存文件错误: {str(e)}"}
            )
            
    except Exception as e:
        logger.error(f"处理保存请求时出错: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"服务器错误: {str(e)}"}
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
        
        logger.info(f"文件已复制到程序目录: {file_path.resolve()}")
        
        # 返回文件在服务器上的路径
        return {
            "success": True,
            "filename": name,
            "file_path": str(file_path.resolve()),  # 返回绝对路径
            "relative_path": f"uploads/{name}",  # 用于前端访问的相对路径
            "url": f"/uploads/{name}"  # 可直接访问的URL
        }
    except Exception as e:
        logger.error(f"文件上传失败: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"文件上传失败: {str(e)}"}
        )
    finally:
        await file.close()

@file_router.post("/read-record", summary="读取指定路径的记录文件")
async def read_record(request: FilePathRequest):
    try:
        file_path = request.file_path
        logger.info(f"尝试读取文件: {file_path}")
        
        # 安全检查
        if not is_safe_path(ALLOWED_BASE_DIR, file_path):
            logger.warning(f"路径安全检查失败: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="路径不允许访问"
            )
        
        # 检查文件是否存在
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logger.warning(f"文件不存在: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="文件不存在"
            )
            
        # 检查是否是文件
        if not file_path_obj.is_file():
            logger.warning(f"不是文件: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="指定路径不是文件"
            )
        
        # 检查文件大小，防止过大文件
        file_size = file_path_obj.stat().st_size
        max_size = 10 * 1024 * 1024  # 10MB
        if file_size > max_size:
            error_msg = f"文件过大: {file_path} (大小: {file_size} bytes, 最大允许: {max_size} bytes)"
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
            
            logger.info(f"成功读取文件: {file_path} (大小: {len(content)} bytes)")

            return JSONResponse({
                "success": True,
                "content": content
            })
            
        except Exception as e:
            logger.error(f"读取文件错误: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"读取文件失败: {str(e)}"
            )
            
    except HTTPException:
        # 重新抛出已定义的HTTP异常
        raise
    except Exception as e:
        logger.error(f"处理请求错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"服务器错误: {str(e)}"
        )
    