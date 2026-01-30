from fastapi import APIRouter, Request, UploadFile, HTTPException, status
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from pathlib import Path
import os, json, uuid, shutil, fastapi, asyncio
from config import logger, ALLOWED_BASE_DIR, UPLOAD_DIR, RUN_DIR, BASE_DATA_DIR

file_router = APIRouter()

# Define request model
class FilePathRequest(BaseModel):
    file_path: str

def is_safe_path(base_dir: str, file_path: str) -> bool:
    """
    Check if the file path is within the allowed base directory to prevent path traversal attacks
    """
    base_path = Path(base_dir).resolve()
    resolved_file_path = Path(file_path).resolve()
    
    # Ensure the file path is a subdirectory of the base directory
    return base_path in resolved_file_path.parents or base_path == resolved_file_path

@file_router.post("/save_input_json", summary="api.summary_save_json")
async def save_input_json(request: Request):
    """Save configuration to the input.json file"""
    try:
        logger.info("recieve the save input.json request")
        
        # Parse request data
        try:
            config_data = await request.json()
            raw_filename = config_data.get("filename", "input.json")
            filename = os.path.basename(raw_filename)  # Prevent path injection
            data_len = len(json.dumps(config_data.get("data")))
            logger.info(f"recieve the file name: {filename}")
            logger.info(f"recieve the save request: {data_len} words")
        except Exception as e:
            logger.error(f"parsing JSON fails: {str(e)}")
            return JSONResponse(
                status_code=400,
                content={"success": False, "message_key": "api.err_json_parse"} # 使用 Key
            )
        
        # Save file
        try:
            save_path = Path(RUN_DIR)
            save_path.mkdir(parents=True, exist_ok=True) # Ensure parent directories are created as we
            file_path = save_path / filename
            counter = 0
            if file_path.exists():
                counter = 0
                backup_file = file_path
                # Look for an available backup filename
                while backup_file.exists():
                    name, ext = os.path.splitext(filename)
                    backup_file = save_path / f"{name}_{counter}{ext}"
                    counter += 1
                # Safely back up the old file
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
    """Upload file and copy it to the uploads folder in the program directory"""
    try:
        # Create target file path
        filename = file.filename
        if not filename:
            filename = f"unknown_file_{uuid.uuid4().hex[:8]}"
        
        # Handle duplicate filenames
        file_path = UPLOAD_DIR / filename
        counter = 1
        while file_path.exists():
            name, ext = os.path.splitext(filename)
            name = f"{name}_{counter}{ext}"
            file_path = UPLOAD_DIR / name
            counter += 1
        
        # Save file
        with open(file_path, "wb") as buffer:
            # Read and write in chunks for higher efficiency with large files
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                buffer.write(chunk)
        
        logger.info(f"file is copy to: {file_path.resolve()}")
        
        # Return the file path on the server
        return {
            "success": True,
            "filename": name,
            "file_path": str(file_path.resolve()),  # Absolute path on the server
            "relative_path": f"uploads/{name}",  # Relative path for frontend access
            "url": f"/uploads/{name}"  # FILES URL for direct access
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
        file_path = request.file_path.replace("/get_data_file/", str(BASE_DATA_DIR) + "/")
        logger.info(f"try to read file: {file_path}")
        
        # Security check
        if not is_safe_path(ALLOWED_BASE_DIR, file_path):
            logger.warning(f"file path is unsafe: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="permission denied for this file path"
            )
        
        # Check if file exists
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logger.warning(f"file is unexits: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="file is unexits"
            )
            
        # Check if it is a file
        if not file_path_obj.is_file():
            logger.warning(f"Error: Not a file: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Error: Not a file"
            )
        
        # Check file size to prevent excessively large files
        file_size = file_path_obj.stat().st_size
        max_size = 10 * 1024 * 1024  # 10MB
        if file_size > max_size:
            error_msg = f"Error: too long: {file_path} (Now: {file_size} bytes, Maxium: {max_size} bytes)"
            logger.warning(error_msg)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=error_msg
            )
        
        # Read file content asynchronously
        try:
            async def read_file_async(path: Path) -> str:
                loop = asyncio.get_event_loop()
                # Execute file reading in a thread pool to avoid blocking the event loop
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
        raise
    except Exception as e:
        logger.error(f"responce has some problem: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server has some problem: {str(e)}"
        )
    
@file_router.get("/get_data_file/{file_path:path}")
async def get_data_file(file_path: str):
    # serve files from BASE_DATA_DIR
    full_path = Path(BASE_DATA_DIR) / file_path
    if full_path.exists() and full_path.is_file():
        return FileResponse(full_path)
    return JSONResponse(status_code=404, content={"message": f"File not found: {file_path}"})
    # safe_filename = os.path.basename(filename)
    # file_path = Path(BASE_DATA_DIR) / folder / safe_filename
    # if file_path.exists():
    #     return FileResponse(file_path)
    # return JSONResponse(status_code=404, content={"message": "File not found"})

@file_router.get("/get_config_status")
async def get_config_status(filename: str):
    try:
        # Prevent directory traversal attacks
        safe_filename = os.path.basename(filename)
        target_path = Path(RUN_DIR) / safe_filename
        print(f"DEBUG: The absolute path being attempted is: {target_path.absolute()}")
        print(f"DEBUG: Whether this path exists: {target_path.exists()}")
        if not target_path.exists():
            return JSONResponse(status_code=404, content={"success": False, "detail": "File not found"})

        with open(target_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            
        return config_data # Directly return the configuration content
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "detail": str(e)})
    