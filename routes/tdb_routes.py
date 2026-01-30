from fastapi import APIRouter,Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import asyncio,fastapi
from config import logger, executor, RUN_DIR, BASE_DATA_DIR
from src.main_process.al_worker import ALRunner
from src.main_process.subl_model_assess import subl_assess
import src.generate as generate
from pathlib import Path

tdb_router = APIRouter()
subl_assess_runner:subl_assess = None

# Define request model
class TdbGenerationRequest(BaseModel):
    user: str
    mask: int
    input_file_path: str

@tdb_router.post("/generate_tdb")
async def generate_tdb(
    request: Request,
    data: TdbGenerationRequest
):
    manager = request.app.state.manager
    global subl_assess_runner
    """Generate TDB file"""
    try:
        # Construct or retrieve task ID
        user_id = data.user if data.user else "guest"
        configname = data.input_file_path if data.input_file_path else "input"
        # config_dir = data.get("config", {})
        task_id = f"{user_id}_{configname}"
        data.input_file_path = f"{RUN_DIR}/{configname}.json"

        logger.info(f"Received TDB file generation data: user={data.user}, mask={data.mask}, input.json = {data.input_file_path}")
        
        await manager.create_and_start_task(task_id, f"{RUN_DIR}/{configname}.json")
        loop_runner = manager.tasks.get(task_id)
        loop_runner = manager.tasks.get(task_id)

        # Check if the runner instance is valid
        if not loop_runner:
            logger.error("ALRunner instance not initialized")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Internal server error: uninitialized ALRunner instance   "}
            )
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            executor,
            loop_runner.output_tdb_file,
            data.user,
            data.mask,
            data.input_file_path
        )
        print(result)
        
        if result:
            print(result)
            logger.info(f"TDB file generated successfully: {result['file_path'],result['file_name_tdb']}")
            subl_assess_runner = subl_assess(input_data_file=result['input_data'],
                                             vasp_ml_data_path=result['file_path'] / result['file_name_csv'],
                                             record_path=result['file_path'])
            print(len(subl_assess_runner.site_weight))
            print(78)
            return {
                "success": True, 
                "message": "TDB file generated successfully",
                "file_path": result['file_path'] / result['file_name_tdb'],
                "sublatticeNumber":len(subl_assess_runner.site_weight)
            }
        else:
            logger.error("TDB file generation failed")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "TDB file generation failed"}
            )
            
    except Exception as e:
        logger.error(f"Error occurred while generating TDB file: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Error occurred while generating TDB file: {str(e)}"}
        )
    

@tdb_router.post("/analyze_models")
async def analyze_models(choosen:list[int] = fastapi.Body(...)):
    """Perform model analysis"""
    try:
        logger.info(f"Received sublattice model analysis request: {len(choosen)}")
        
        # Check if the runner instance is valid
        if not subl_assess_runner:
            logger.error(" subl_assess_runner instance is not initialized")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error: subl_assess_runner is not initialized"}
            )
        
        result = subl_assess_runner.get_model_result_raw(choosen)
        
        if result:
            print(result)
            logger.info(f"Model analysis completed")
            return {
                "success": True, 
                "message": "Model analysis completed"
            }
        else:
            logger.error("Model analysis failed")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Model analysis failed"}
            )
            
    except Exception as e:
        logger.error(f"Model analysis failed: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Model analysis failed: {str(e)}"}
        )
    

@tdb_router.post("/plot_base_analyze_models")
async def plot_base_analyze_models():
    """Perform plotting / generating figures"""
    try:
        
        # Check if the runner instance is valid
        if not subl_assess_runner:
            logger.error(" subl_assess_runner instance not initialized")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Error: subl_assess_runner is not initialized"}
            )
        
        # utilize the existing subl_assess_runner to plot
        result = subl_assess_runner.plot_model_result_raw()
        
        if result['state']:
            result['plot_file'] = Path(result['plot_file'])
            print(result['plot_file'])
            logger.info(f"Model analysis plot completed, stored at：{result['plot_file']}")
            fig_name = result['plot_file'].relative_to(BASE_DATA_DIR)
            csv_name = result['score_file'].relative_to(BASE_DATA_DIR)
            return {
                "plot_file": f'/get_data_file/{fig_name}',
                "score_file": f'/get_data_file/{csv_name}',
                "success": True, 
                "message": "Model analysis plot completed"
            }
        else:
            logger.error("Model analysis plotting failed")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Model analysis plotting failed"}
            )
            
    except Exception as e:
        logger.error(f"Failed in plotting: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Failed in plotting: {str(e)}"}
        )
    

class ElementGroupsRequest(BaseModel):
    selected_model: str = ""

# Response body: return a 2D list of elements
class ElementGroupsResponse(BaseModel):
    success: bool = True
    element_groups: list[list[str]]
    message: str = ""

@tdb_router.post("/get_element_groups", response_model=ElementGroupsResponse)
async def get_element_groups(req: ElementGroupsRequest):
    # Mock a 2D list returned from the backend
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
        "message": f"elements groups responce for {req.selected_model}"
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
    # Actually needs to be read from a database or config file
    print(f"model {req.selected_model}: delete elements {req.need_del}, fixed (retained) elements {req.fix}, waiting to analysis {req.analys}")

    
    return {
        "success": True,
        "message": "Element filtering has taken effect"
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
    # Actual logic: update the model's element configuration
    print(f"model {req.selected_model['model_name']} files will be save in {req.output_path}, elements: {req.element_groups},{req.file_format},waiting to analysis{req.file_format}")
    temp_summary = req.selected_model['model_name']
    temp_summary = temp_summary.split(".")
    if len(temp_summary) != 2:
        return{
            "success": False,
            "message": f"file name has something wrong \"4_A_B_C_D_A.csv\",\n now is {req.selected_model['model_name']}\n please check it"
        }
    temp_summary = temp_summary[0].split("_")
    model = []
    model.append(temp_summary[0])
    model.append(":".join(temp_summary[1:]))
    model[0] = int(model[0])
    target_path = Path(req.output_path)
    site_element_new = req.element_groups
    print(site_element_new)
        
    # Check if the runner instance is valid
    if not subl_assess_runner:
        logger.error(" subl_assess_runner instance not initialized")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Error: subl_assess_runner is not initialized"}
        )
    
    subl_assess_runner.output_all_tdb_file_assessed(candidate_model=[model],
                                    site_elements=site_element_new, tor=5, save_path=target_path)
    
    return {
        "success": True,
        "message": "output TDB file with assessed model completed"
    }