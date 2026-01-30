import json
import os
import random
import time
import asyncio
import logging
from typing import List, Optional
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from concurrent.futures import ThreadPoolExecutor

import src.POSCAR_generate
from src.class_def import Phase
from src.tdb_generator import tdb_generate_from_MLmodel

from config import BASE_DATA_DIR
import traceback

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ALRunner:
    def __init__(self, task_id: str, config_dir: str, executor=None):
        self.task_id = task_id
        self.executor = executor # 保存传入的全局线程池

        self.input_json = Path(config_dir)
        # self.file_path = os.path.join(working_dir, "record.txt")
        # self.iter_csv_path = os.path.join(working_dir, "iter.csv")

        self.running = False
        self.paused = False
        self.started = False

        self.main_task: Optional[asyncio.Task] = None
        self.subscribers: List[WebSocket] = []
        self.phase: Optional[Phase] = None
        self.iter: int = 0
        self.process: int = 0
        self.data: Optional[dict] = None
        self.state_lock = asyncio.Lock()  # 关键修复：异步锁保护状态修改
        self.stop_event = asyncio.Event()  # 新增：用于快速通知主循环停止
        self.executor: Optional[ThreadPoolExecutor] = None  # 线程池初始化为None
        self.auto_recovery_attempts = 0  # 自动恢复尝试次数，避免无限循环
        self.max_auto_recovery = 3  # 最大自动恢复次数
        
    def reset_state(self):
        """重置状态，包括线程池"""
        self.running = False
        self.paused = False
        self.started = False
        self.stop_event.clear()
        # 取消现有任务
        if self.main_task and not self.main_task.done():
            self.main_task.cancel()
        # 释放Phase对象和数据，强制垃圾回收
        self.phase = None
        self.data = None
        # 关闭并清除线程池（如果存在）
        if self.executor:
            self.executor.shutdown(wait=False)
            self.executor = None
            
    def delete_last_line(self):
        """删除record.txt的最后一行"""
        try:
            if not os.path.exists(self.file_path) or os.path.getsize(self.file_path) == 0:
                logger.warning("record.txt为空或不存在，无法删除最后一行")
                return False
                
            # 读取所有行并排除最后一行
            with open(self.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            if len(lines) <= 1:
                # 如果只有一行或为空，清空文件
                with open(self.file_path, 'w', encoding='utf-8') as f:
                    f.write('')
            else:
                # 写入除最后一行外的所有内容
                with open(self.file_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines[:-1])
            
            logger.info("已删除record.txt的最后一行")
            return True
        except Exception as e:
            logger.error(f"删除最后一行失败: {e}")
            return False
        
    def output_tdb_file(self, user:str, mask:int, data_file:str=''):
        print("im in outer: "+data_file)
        if data_file == '':
            data_file = self.input_json
        with open(data_file, 'r', encoding='utf-8') as f:
            # data = json.load(f, object_hook=lambda d: {k.upper(): v for k, v in d.items()})
            data = json.load(f)
        pkl_phase_path = BASE_DATA_DIR / Path(self.data["AL_set"]["pkl_phase_path"])
        file_path = BASE_DATA_DIR / Path(data["record_path"])
        print(pkl_phase_path)
        # 读取或初始化迭代状态
        if os.path.isfile(file_path/'record.txt'):
            iter, process = self.read_last_line(file_path=file_path/'record.txt')
            print(f"即将读取 {pkl_phase_path}/model_{iter:06d}_{process}.pd")
            # phase = Phase.load(f'{pkl_phase_path}/model_{iter:06d}_{process}.pd')
        else:
            logger.error(f"啊噢！record.txt走丢了")
            return False
        try:
            file_path = f'{file_path}/tdb_file'
            print(file_path)
            tdb_file = tdb_generate_from_MLmodel(pkl_path=pkl_phase_path,
                        iter=iter, process=process,
                        user=user, mask=mask, file_path=file_path)
            # tdb_file={'file_path':...,'file_name_tdb':...,'file_name_csv':...}
            return {'input_data':data_file,**tdb_file}
        except Exception as e:
            logger.error(f"输出tdb文件失败: {e}")
            return False
    
    async def auto_recover_and_restart(self):
        """自动恢复并重新启动循环"""
        async with self.state_lock:
            if self.auto_recovery_attempts >= self.max_auto_recovery:
                error_msg = f"已达到最大自动恢复次数({self.max_auto_recovery})，请手动处理"
                logger.error(error_msg)
                await self.send_message(json.dumps({
                    "type": "error", 
                    "content": error_msg
                }))
                self.reset_state()
                return
            
            self.auto_recovery_attempts += 1
            recovery_msg = f"尝试自动恢复（第{self.auto_recovery_attempts}次）..."
            logger.info(recovery_msg)
            await self.send_message(json.dumps({
                "type": "status-update", 
                "content": recovery_msg
            }))
        
        # 删除最后一行记录
        delete_success = self.delete_last_line()
        if not delete_success:
            await self.send_message(json.dumps({
                "type": "error", 
                "content": "自动恢复失败：无法修改record.txt"
            }))
            return
        
        # 重置状态并重新启动
        self.reset_state()
        async with self.state_lock:
            self.running = True
            self.started = True
            self.main_task = asyncio.create_task(self.main_loop())
        
        await self.send_message(json.dumps({
            "type": "status-update", 
            "content": "自动恢复完成，已重新启动AL循环"
        }))
        logger.info("自动恢复并重启完成")
        
    async def send_message(self, message: str):
        """向所有订阅的WebSocket发送消息"""
        # 确保消息是JSON格式，便于前端处理
        import json
        try:
            # 如果不是JSON，包装成消息对象
            if not message.startswith('{'):
                message = json.dumps({"type": "message", "content": message})
            for websocket in self.subscribers[:]:  # 使用副本避免修改时迭代出错
                try:
                    await asyncio.wait_for(websocket.send_text(message), timeout=1.0)
                except Exception as e:
                    logger.error(f"发送消息给WebSocket失败: {e}")
                    self.unsubscribe(websocket)
        except Exception as e:
            logger.error(f"准备消息时出错: {e}")
    
    def subscribe(self, websocket: WebSocket):
        """订阅WebSocket更新"""
        if websocket not in self.subscribers:
            self.subscribers.append(websocket)
            logger.info(f"新的WebSocket订阅，当前订阅数: {len(self.subscribers)}")
    
    def unsubscribe(self, websocket: WebSocket):
        """取消WebSocket订阅"""
        if websocket in self.subscribers:
            self.subscribers.remove(websocket)
            logger.info(f"WebSocket取消订阅，当前订阅数: {len(self.subscribers)}")
    
    async def toggle_pause(self):
        """关键修复：用异步锁保护状态修改，确保线程安全"""
        async with self.state_lock:
            self.paused = not self.paused
            state = "暂停" if self.paused else "继续"
            logger.info(f"AL循环已{state}")
            await self.send_message(f"状态更新: AL循环已{state}")
            return self.paused
    
    async def stop(self):
        """停止逻辑：确保线程池正确关闭"""
        async with self.state_lock:
            if not self.running and not self.started:
                logger.info("没有运行中的任务需要停止")
                return True
                
            self.running = False
            self.paused = False
            self.started = False
            self.stop_event.set()
        
        await self.send_message(json.dumps({
            "type": "status", 
            "status": "stopping",
            "message": "正在终止任务..."
        }))
        # 取消主任务
        if self.main_task and not self.main_task.done():
            self.main_task.cancel()
            logger.info("主任务已被强制取消")
        # 等待任务结束
        try:
            await asyncio.wait_for(self._wait_for_task_end(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning("任务取消超时")
        
        # 关闭线程池（在stop中明确关闭，而非main_loop的finally）
        if self.executor:
            self.executor.shutdown(wait=False)
            self.executor = None
            logger.info("线程池已关闭")
        
        await self.send_message(json.dumps({
            "type": "status", 
            "status": "stopped",
            "message": "任务已终止"
        }))
        
        logger.info("停止流程完成")
        return True
    
    async def _wait_for_task_end(self):
        """等待任务结束的辅助函数"""
        if self.main_task and not self.main_task.done():
            try:
                await self.main_task
            except asyncio.CancelledError:
                logger.info("主任务已成功取消")
            except Exception as e:
                logger.error(f"任务结束时发生错误: {e}")

    def init_process(self, data):
        """初始化过程，与原始代码保持一致"""
        logger.info("开始初始化AL循环")
        
        phase_name = data["phase_name"]
        al_set = data["AL_set"]
        record_path = BASE_DATA_DIR / Path(data["record_path"]) # 已经由 Manager 确保唯一性

        ELEMENT_SYMBOLS = [
            'H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne',
            'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar', 'K', 'Ca',
            'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn',
            'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr', 'Rb', 'Sr', 'Y', 'Zr',
            'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn',
            'Sb', 'Te', 'I', 'Xe', 'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd',
            'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb',
            'Lu', 'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg',
            'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn', 'Fr', 'Ra', 'Ac', 'Th',
            'Pa', 'U', 'Np', 'Pu', 'Am', 'Cm', 'Bk', 'Cf', 'Es', 'Fm',
            'Md', 'No', 'Lr', 'Rf', 'Db', 'Sg', 'Bh', 'Hs', 'Mt', 'Ds',
            'Rg', 'Cn', 'Nh', 'Fl', 'Mc', 'Lv', 'Ts', 'Og'
        ]
        
        # 3. 执行结构转换逻辑 (POSCAR 生成)
        # 脱钩点：所有路径都直接从 data 键值对获取
        flag_to_primitive = data.get("structure_convert_to_primitive", "N").upper() in ['Y', 'YES']
        
        stru, replace_pattern = src.POSCAR_generate.replace_wyckoff(
            BASE_DATA_DIR / Path(data["structure_file"]), 
            replacement_sequence=ELEMENT_SYMBOLS,
            convert_to_primatice=flag_to_primitive, 
            output_file=BASE_DATA_DIR / Path(data["structure_out_file"])
        )
        
        # 4. 构建 Phase 对象
        # 注意：这里我们只传参，不再管理 record.txt 的句柄
        model = data["tdb_model"]
        site_holder = model["site_holder"]
        site_holder_end = [replace_pattern[ord(i)-65] for i in site_holder]

        phase = Phase(
            iter=0, 
            name=phase_name, 
            structure=stru, 
            tdb_model=model, 
            record_path=record_path
        )
        phase.tdb_model["site_holder"] = site_holder_end
        # 5. 特征表整合 (机器学习准备)
        eigen_table = self._build_eigen_table(al_set["descriptor"])
        
        # 6. 初始化 Phase 的机器学习环境
        phase.X_table_init(
            al_set["ML_model"], 
            self._parse_hyper_params(al_set.get("ML_hyper_parameters", "")), 
            al_set["ML_style"],
            eigen_table, 
            al_set["eigen_weight"], 
            al_set["normalizer"],
            BASE_DATA_DIR / Path(al_set["generate_DFT_path"]), 
            BASE_DATA_DIR / Path(al_set["calced_DFT_path"]),
            BASE_DATA_DIR / Path(al_set["pkl_phase_path"]), 
            al_set["pkl_show_control"], 
            al_set["quest"]
        )
        
        # 7. 生成初始采样点
        random_n = data.get("init_random_n", 5)
        temp = random.sample(phase.pool, random_n)
        for i in phase.tdb_model["sys_species"]:
            temp.append(':'.join([i] * len(phase.tdb_model["comp"])))
        
        phase.upload(temp)
        logger.info(f"初始上传点: {temp}")
        
        # 8. 记录初始化数据 (不再在函数内 open, 保持逻辑纯粹)
        self._initialize_record_files(record_path)
        
        return phase


    def _initialize_record_files(self, record_path):
        """辅助方法：初始化记录文件"""
        os.makedirs(record_path, exist_ok=True)
        record_file = os.path.join(record_path, "record.txt")
        with open(record_file, 'w', encoding='utf-8') as f:
            f.write("0 0\n")  # 初始迭代状态
        # 初始化 iter.csv 文件
        iter_csv_path = os.path.join(record_path, "iter.csv")
        iter_df = pd.DataFrame(columns=[
            "training_data_amount","RMSE(train)","RMSE(test)","fold_num_r2","r2_score","fold_num_r2","RMSE_score"
        ])
        iter_df.to_csv(iter_csv_path, index=False)
        logger.info(f"已初始化记录文件: {record_file} 和 {iter_csv_path}")

    def _build_eigen_table(self, descripter):
        """辅助方法：解耦特征表构建"""
        eigen_table = pd.DataFrame(columns=["symbol"])
        for key in descripter:
            logger.info(f"处理描述符: {key}, {descripter[key]}")
            selected_cols = [descripter[key]["index_name"]] + descripter[key]["col_name"]
            load_temp = pd.read_csv(key)
            print(load_temp)
            load_temp = load_temp[selected_cols]
            load_temp.rename(columns={selected_cols[0]: "symbol"}, inplace=True)
            load_temp["symbol"] = load_temp["symbol"].str.upper()
            eigen_table = pd.merge(
                load_temp,
                eigen_table,
                on="symbol",
                how='outer'
            )
        return eigen_table

    def _parse_hyper_params(self, param_str):
        """辅助方法：安全解析参数"""
        try:
            return eval(param_str) if param_str.strip() else {}
        except:
            return {}
    
    def read_last_line(self, file_path:str='') -> tuple[int, int]:
        """读取文件最后一行并解析为整数对 (iter, process)"""
        try:
            if file_path =='':
                file_path = self.file_path
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                return 0, 0

            with open(file_path, 'rb') as f:
                offset = -8  # 初始偏移量
                filesize = os.path.getsize(file_path)
                
                while -offset < filesize:
                    try:
                        f.seek(offset, 2)
                    except OSError:
                        f.seek(0)
                        break
                    data = f.read()
                    lines = data.splitlines()
                    if len(lines) >= 2:
                        last_line = lines[-1].decode().strip()
                        break
                    offset *= 2
                else:
                    f.seek(0)
                    lines = f.read().splitlines()
                    last_line = lines[-1].decode().strip() if lines else ''

            parts = last_line.split()
            if len(parts) != 2:
                raise ValueError(f"最后一行格式错误: {last_line}")

            iter = int(parts[0])
            process = int(parts[1])
            return iter, process
        except Exception as e:
            logger.error(f"读取最后一行失败: {e}")
            return 0, 0
    
    def write_log(self, sentence: str):
        """写入日志到文件"""
        try:
            with open(self.file_path, 'a+') as f:
                f.write(sentence)
        except Exception as e:
            logger.error(f"写入日志失败: {e}")
    
    async def main_loop(self):
        """AL循环主逻辑，改造为异步执行"""
        logger.info("开始AL主循环")
        try:
            # # 每次启动时创建新的线程池
            # self.executor = ThreadPoolExecutor(max_workers=1)
            # logger.info("已创建新的线程池")

            # 读取配置数据
            with open(self.input_json, 'r', encoding='utf-8') as f:
                # self.data = json.load(f, object_hook=lambda d: {k.upper(): v for k, v in d.items()})
                self.data = json.load(f)
            
            al_set = self.data["AL_set"]
            pkl_phase_path = BASE_DATA_DIR / Path(self.data["AL_set"]["pkl_phase_path"])
            os.makedirs(pkl_phase_path, exist_ok=True)
            self.file_path = BASE_DATA_DIR / Path(self.data["record_path"])
            os.makedirs(self.file_path, exist_ok=True)
            self.file_path = self.file_path / Path('record.txt')
            
            # 读取或初始化迭代状态
            if os.path.isfile(self.file_path):
                self.iter, self.process = self.read_last_line()
            else:
                self.iter, self.process = 0, 0
            
            # 初始化过程
            if (self.iter == 0) and (self.process == 0):
                await self.send_message("开始初始化AL循环...")
                # 使用线程池执行同步初始化，可被中断
                self.phase = await asyncio.get_event_loop().run_in_executor(
                    self.executor, 
                    self.init_process, 
                    self.data
                )
                self.write_log(f"{self.iter} {self.process}\n")
                self.phase.save(f'{pkl_phase_path}/model_{self.iter:06d}_{self.process}.pd')
                self.process = 1
                self.write_log(f"{self.iter} {self.process}\n")
                await self.send_message("初始化完成")
            else:
                # 加载已有的模型
                await self.send_message(f"加载模型: model_{self.iter:06d}_{self.process}.pd")
                self.phase = Phase.load(f'{pkl_phase_path}/model_{self.iter:06d}_{self.process}.pd')
            
            # 主循环
            async with self.state_lock:
                running = self.running
            while running:
                # 快速检查是否需要停止（优先响应stop_event）
                if self.stop_event.is_set():
                    break
                
                # 检查运行状态
                async with self.state_lock:
                    running = self.running
                    paused = self.paused
                if not running:
                    break
                
                # 处理暂停（短间隔轮询）
                while paused:
                    await asyncio.sleep(0.1)  # 更短的检查间隔
                    if self.stop_event.is_set():
                        break
                    async with self.state_lock:
                        paused = self.paused
                
                if not running:
                    break
                
                
                try:
                    # 状态0: 完成模型训练，生成新的quest
                    if self.process == 0:
                        await self.send_message(f"迭代 {self.iter}: 生成新的查询点...")
                        self.phase.quest = al_set["quest"]
                        
                        # 执行凸包分析并生成新的DFT点
                        await asyncio.get_event_loop().run_in_executor(
                            self.executor, 
                            self.phase.convex_analy
                        )
                        await asyncio.get_event_loop().run_in_executor(
                            self.executor, 
                            self.phase.generate_DFT_POSCAR
                        )
                        
                        self.process = 1
                        # 保存模型
                        if self.phase.pkl_show_control.upper() in ['HIGH']:
                            self.phase.save(f'{pkl_phase_path}/model_{self.iter:06d}_{self.process}.pd')
                        
                        self.write_log(f"{self.iter} {self.process}\n")
                        await self.send_message(f"迭代 {self.iter}: 已生成新的DFT计算任务")
                    
                    # 状态1: 等待VASP计算完成
                    elif self.process == 1:
                        await self.send_message(f"迭代 {self.iter}: 等待DFT计算完成...")
                        
                        # 准备计算目录
                        calced_dir = f"{self.phase.calced_DFT_path}/iter.{self.iter:06d}"
                        os.makedirs(calced_dir, exist_ok=True)
                        vasp_calc_end = f"{calced_dir}/calc.txt"
                        print(vasp_calc_end)
                        
                        # 等待VASP计算完成
                        while running and not self.stop_event.is_set():
                            if os.path.isfile(vasp_calc_end):
                                break
                            # 极短的等待时间，确保能快速响应停止
                            await asyncio.sleep(0.1)
                            async with self.state_lock:
                                paused = self.paused
                                running = self.running
                            
                            # 处理暂停
                            while paused and running and not self.stop_event.is_set():
                                await asyncio.sleep(0.1)
                                async with self.state_lock:
                                    paused = self.paused
                        
                        if self.stop_event.is_set():
                            break
                        if not running:
                            break
                        
                        # 处理新的VASP数据
                        await asyncio.get_event_loop().run_in_executor(
                            self.executor, 
                            self.phase.add_calced_points, 
                            vasp_calc_end
                        )
                        
                        self.process = 2
                        # 保存模型
                        if self.phase.pkl_show_control.upper() in ['LOW', "MEDIUM", "HIGH"]:
                            self.phase.save(f'{pkl_phase_path}/model_{self.iter:06d}_{self.process}.pd')
                        
                        self.write_log(f"{self.iter} {self.process}\n")
                        await self.send_message(f"迭代 {self.iter}: DFT计算结果已处理")
                    
                    # 状态2: 执行ML模型训练
                    elif self.process == 2:
                        await self.send_message(f"迭代 {self.iter}: 开始机器学习模型训练...")
                        # 执行ML训练
                        await asyncio.get_event_loop().run_in_executor(
                                self.executor, 
                                self.phase.ML
                            )

                        # 更新迭代次数
                        self.iter += 1
                        self.process = 0
                        self.phase.iter = self.iter
                        
                        # 保存模型
                        if self.phase.pkl_show_control.upper() in ["MEDIUM", "HIGH"]:
                            self.phase.save(f'{pkl_phase_path}/model_{self.iter:06d}_{self.process}.pd')
                        
                        await self.send_message(f"[模型保存] 已保存到 {pkl_phase_path}/model_{self.iter:06d}_{self.process}.pd")
                        
                        self.write_log(f"{self.iter} {self.process}\n")
                        await self.send_message(f"迭代 {self.iter-1}: 机器学习模型训练完成，准备下一迭代")
                
                except Exception as e:
                    # 获取详细的错误堆栈信息
                    full_traceback = traceback.format_exc()
                    
                    # 提取文件名和行号的简短描述（方便显示给用户）
                    # tb_next 之后是跳过当前这个 try-except 所在的函数层级，定位到报错点
                    tb = e.__traceback__
                    while tb.tb_next:
                        tb = tb.tb_next
                    filename = os.path.basename(tb.tb_frame.f_code.co_filename)
                    line_no = tb.tb_lineno
                    
                    short_error = f"出错文件: {filename}, 行号: {line_no}, 错误: {str(e)}"
                    error_msg = f"迭代过程出错: {short_error}"
                    
                    logger.error(f"详细堆栈:\n{full_traceback}") # 日志记详细的
                    
                    await self.send_message(json.dumps({
                        "type": "error",
                        "content": error_msg,  # 发送给前端包含文件和行号的信息
                        "traceback": full_traceback # 可选：把完整堆栈也发过去以便调试
                    }))
                    # error_msg = f"迭代过程出错: {str(e)}"
                    # logger.error(error_msg)
                    # await self.send_message(json.dumps({
                    #     "type": "error",
                    #     "content": error_msg
                    # }))
                    # 检测特定错误：数组可写性问题
                    if "cannot set WRITEABLE flag to True of this array" in str(e):
                        await self.send_message(json.dumps({
                            "type": "status-update",
                            "content": "检测到数组可写性错误，尝试自动恢复..."
                        }))
                        # 触发自动恢复
                        await self.auto_recover_and_restart()
                        return  # 退出当前循环，因为已启动新循环
                    
                    # 其他错误处理
                    async with self.state_lock:
                        self.paused = True
                    await asyncio.sleep(1)

                async with self.state_lock:
                    running = self.running
            
            await self.send_message("AL循环已退出")
            logger.info("AL循环正常结束")
            
        except Exception as e:
            error_msg = f"AL主循环出错: {str(e)}"
            logger.error(error_msg)
            await self.send_message(error_msg)
        finally:
            async with self.state_lock:
                self.running = False
                self.started = False
            self.stop_event.clear()  # 重置事件
            self.executor.shutdown(wait=False)
