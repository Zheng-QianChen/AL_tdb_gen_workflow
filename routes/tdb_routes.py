from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import asyncio,fastapi
from config import logger, executor
from src.main_process.subl_model_assess import subl_assess
import src.generate as generate
from pathlib import Path

tdb_router = APIRouter()
subl_assess_runner:subl_assess = None

# 定义请求模型
class TdbGenerationRequest(BaseModel):
    user: str
    mask: int
    input_file_path: str

@tdb_router.post("/generate_tdb")
async def generate_tdb(request: TdbGenerationRequest):
    global subl_assess_runner
    """生成TDB文件"""
    try:
        logger.info(f"收到TDB文件生成请求: user={request.user}, mask={request.mask}, input.json = {request.input_file_path}")
        
        # 检查runner实例是否有效
        if not runner:
            logger.error("ALRunner实例未初始化")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "服务器内部错误: ALRunner未初始化"}
            )
        
        # 调用ALRunner的output_tdb_file方法（内部已处理phase初始化）
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            executor,
            runner.output_tdb_file,
            request.user,
            request.mask,
            request.input_file_path
        )
        
        if result:
            print(result)
            logger.info(f"TDB文件生成成功: {result['file_path'],result['file_name_tdb']}")
            subl_assess_runner = subl_assess(input_data_file=result['input_data'],
                                             vasp_ml_data_path=result['file_path'] / result['file_name_csv'],
                                             record_path=result['file_path'])
            print(len(subl_assess_runner.site_weight))
            return {
                "success": True, 
                "message": "TDB文件生成成功",
                "file_path": result['file_path'] / result['file_name_tdb'],
                "sublatticeNumber":len(subl_assess_runner.site_weight)
            }
        else:
            logger.error("TDB文件生成失败")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "TDB文件生成失败"}
            )
            
    except Exception as e:
        logger.error(f"生成TDB文件时发生错误: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"生成TDB文件错误: {str(e)}"}
        )
    

@tdb_router.post("/analyze_models")
async def analyze_models(choosen:list[int] = fastapi.Body(...)):
    """进行模型分析"""
    try:
        logger.info(f"收到亚点阵模型分析请求: {len(choosen)}")
        
        # 检查runner实例是否有效
        if not subl_assess_runner:
            logger.error(" subl_assess_runner 实例未初始化")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "服务器内部错误: subl_assess_runner 未初始化"}
            )
        
        # 调用ALRunner的output_tdb_file方法（内部已处理phase初始化）
        result = subl_assess_runner.get_model_result_raw(choosen)
        
        if result:
            print(result)
            logger.info(f"模型分析已完成")
            return {
                "success": True, 
                "message": "模型分析已完成"
            }
        else:
            logger.error("模型分析失败")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "模型分析失败"}
            )
            
    except Exception as e:
        logger.error(f"模型分析时发生错误: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"模型分析时发生错误: {str(e)}"}
        )
    

@tdb_router.post("/plot_base_analyze_models")
async def plot_base_analyze_models():
    """进行绘图"""
    try:
        # logger.info(f"收到亚点阵模型分析请求: {len(choosen)}")
        
        # 检查runner实例是否有效
        if not subl_assess_runner:
            logger.error(" subl_assess_runner 实例未初始化")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "服务器内部错误: subl_assess_runner 未初始化"}
            )
        
        # 调用ALRunner的output_tdb_file方法（内部已处理phase初始化）
        result = subl_assess_runner.plot_model_result_raw()
        
        if result['state']:
            result['plot_file'] = Path(result['plot_file'])
            print(result['plot_file'])
            logger.info(f"模型分析图已完成，存储位置为：{result['plot_file']}")
            fig_name = result['plot_file'].name
            return {
                "plot_file": f'/static/fig/{fig_name}',
                "success": True, 
                "message": "模型分析已完成"
            }
        else:
            logger.error("模型分析失败")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "模型分析失败"}
            )
            
    except Exception as e:
        logger.error(f"绘图时发生错误: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"绘图时发生错误: {str(e)}"}
        )
    

class ElementGroupsRequest(BaseModel):
    selected_model: str = ""

# 响应体：返回元素二维列表
class ElementGroupsResponse(BaseModel):
    success: bool = True
    element_groups: list[list[str]]
    message: str = ""

@tdb_router.post("/get_element_groups", response_model=ElementGroupsResponse)
async def get_element_groups(req: ElementGroupsRequest):
    # 模拟后端返回的二维列表（实际需从数据库/配置文件读取）
    print(req.selected_model)
    model_summary = req.selected_model.split('.')[0]
    model_summary = model_summary.split('_')
    model = []
    model.append(model_summary[0])
    model.append(':'.join(model_summary[1:]))
    mock_element_groups = generate.get_model_site_elements(model=model, elements=subl_assess_runner.site_elements)
    # mock_element_groups = [
    #     ['H','He','Li','Be','B'],
    #     ['Li','Be','C'],
    #     ['Li','Be'],
    #     ['Li','Be','O'],
    #     ['Li','Be','N'],
    #     ['Li','Be','B']
    # ]
    return {
        "success": True,
        "element_groups": mock_element_groups,
        "message": f"为模型{req.selected_model}返回元素组"
    }

class FilterSubmitRequest(BaseModel):
    selected_model: str
    analys: list[list[str]]
    need_del: list[list[str]]
    fix: list[list[str]]

class FilterSubmitResponse(BaseModel):
    success: bool = True
    message: str = ""

@tdb_router.post("/submit_filtered_elements", response_model=FilterSubmitResponse)
async def submit_filtered_elements(req: FilterSubmitRequest):
    print("im in /submit_filtered_elements")
    # 实际逻辑：更新模型的元素配置（如写入数据库/文件）
    print(f"模型{req.selected_model}删除元素：{req.need_del},保留元素{req.fix},待分析元素{req.analys}")

    
    return {
        "success": True,
        "message": "元素过滤已生效"
    }


class AmodelTdbGenerateRequest(BaseModel):
    output_path: str
    selected_model: dict
    element_groups: list[list[str]]
    include_metrics: bool
    file_format: str

class AmodelTdbGenerateResponse(BaseModel):
    success: bool = True
    message: str = ""

@tdb_router.post("/tdb_generate_model_assessed", response_model=AmodelTdbGenerateResponse)
async def tdb_generate_model_assessed(req: AmodelTdbGenerateRequest):
    print("im in /tdb_generate_model_assessed")
    # 实际逻辑：更新模型的元素配置（如写入数据库/文件）
    print(f"模型{req.selected_model['model_name']}输出地址{req.output_path}元素：{req.element_groups},{req.file_format},待分析元素{req.file_format}")
    temp_summary = req.selected_model['model_name']
    temp_summary = temp_summary.split(".")
    if len(temp_summary) != 2:
        return{
            "success": False,
            "message": f"文件名有问题，模板为\"4_A_B_C_D_A.csv\",\n现在为：{req.selected_model['model_name']}\n请检查是否与自动设置的一致。"
        }
    temp_summary = temp_summary[0].split("_")
    model = []
    model.append(temp_summary[0])
    model.append(":".join(temp_summary[1:]))
    model[0] = int(model[0])
    target_path = Path(req.output_path)
    site_element_new = req.element_groups
    print(site_element_new)
        
    # 检查runner实例是否有效
    if not subl_assess_runner:
        logger.error(" subl_assess_runner 实例未初始化")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "服务器内部错误: subl_assess_runner 未初始化"}
        )
    
    subl_assess_runner.output_all_tdb_file_assessed(candidate_model=[model],
                                    site_elements=site_element_new, tor=5, save_path=target_path)
    
    return {
        "success": True,
        "message": "输出完成"
    }