
// 控制台功能实现
const btnStart = document.getElementById('btnStart');
const btnPause = document.getElementById('btnPause');
const btnStop = document.getElementById('btnStop');
const btnRefresh = document.getElementById('btnRefresh');
const btnReloadInput = document.getElementById('btnReloadInput');
const statusDiv = document.getElementById('status');
const logDiv = document.getElementById('log');

let activeConfigName = 'input.json'; // 默认监控文件名
let ws;
let reconnectInterval;
let statusCheckInterval;
let startTime = null;
let runtimeInterval = null;
let recordPath = null; // 存储从input.json获取的record_path（文件系统路径）
let fetchTimeout = null; // 用于超时控制

btnStart.onclick = doStart;

// --- 核心逻辑：UI 更新函数 ---
// 该函数是所有数据流的终点，实现数据驱动界面
function updateUIWithConfig(data) {
    if (!data) return;

    // 1. 定义映射关系
    const statusMappings = [
        { id: 'phase-name', path: 'phase_name', defaultValue: '未设置' },
        { id: 'ml-model', path: 'AL_set.ML_model', defaultValue: '未设置' }
    ];

    // 2. 更新基础文本信息
    statusMappings.forEach(item => {
        const value = item.path.split('.').reduce((obj, key) => {
            return obj && obj[key] !== undefined ? obj[key] : undefined;
        }, data);
        
        const element = document.getElementById(item.id);
        if (element) {
            element.textContent = value !== undefined ? value : item.defaultValue;
        }
    });

    // 3. 处理记录文件路径联动
    if (data.record_path) {
        // 更新全局 recordPath，供 readRecordFile 使用
        recordPath = data.record_path + '/record.txt';
        readRecordFile(); 
    } else {
        recordPath = null;
        document.getElementById('current-iteration').textContent = '无路径';
        document.getElementById('current-operation-number').textContent = '无路径';
    }
}

// --- 接口调用：获取系统状态 ---
async function fetchSystemStatus(filename = activeConfigName) {
    // 只有在主动刷新或初次加载时显示“加载中”
    // resetLoadingState(); 

    if (fetchTimeout) clearTimeout(fetchTimeout);
    const abortController = new AbortController();
    fetchTimeout = setTimeout(() => abortController.abort(), 10000);

    try {
        // 【改进】：通过查询参数指定文件名，支持并发监控不同配置
        const response = await fetch(`/get_config_status?filename=${encodeURIComponent(filename)}`, { 
            signal: abortController.signal 
        });

        if (!response.ok) throw new Error(`HTTP错误: ${response.status}`);
        
        const data = await response.json();
        updateUIWithConfig(data);
        
    } catch (error) {
        console.error('获取系统状态失败:', error);
        // 如果失败，更新 UI 反馈
        const phaseEl = document.getElementById('phase-name');
        if (phaseEl) phaseEl.textContent = error.name === 'AbortError' ? '超时' : '连接失败';
    }
}

// 更改input.json配置文件的函数
async function loadSpecificConfig() {
    const filenameInput = document.getElementById('target-config-file');
    const filename = filenameInput.value.trim();
    if (!filename) {
        alert("请输入文件名");
        return;
    }

    const btn = event.currentTarget;
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Loading...';

    try {
        // const response = await fetch('/get_config_status', {
        //     method: 'POST',
        //     headers: { 'Content-Type': 'application/json' },
        //     body: JSON.stringify({ filename: filename })
        // });
        const response = await fetch(`/get_config_status?filename=${encodeURIComponent(filename)}`);

        
        if (response.ok) {
            // 成功后，刷新系统状态显示（如 ML 模型名、当前相名等）
            activeConfigName = filename; // 更新当前监控的文件名
            // 如果后端直接返回了新配置的内容，直接更新 UI
            const data = await response.json();
            activeConfigName = filename;
            if (data) {
                updateUIWithConfig(data);
                initWebSocket(filename);
                const newUrl = `${window.location.pathname}?task=${encodeURIComponent(filename)}`;
                window.history.pushState({ path: newUrl }, '', newUrl);
                addToLog(`监控任务已切换为: ${filename}`, 'info');
            } else {
                alert("加载失败: 文件不存在或后端未定义该路由");
            }
            // 可以在控制台打印一行日志
            addToLog(`系统已成功切换配置文件为: ${filename}`, 'info');
            if (typeof showAlert === 'function') {
                showAlert(getI18nText('api.load_success', '配置加载成功'), 'success');
            }
        } else {
            alert("加载失败: " + (result.detail || "文件不存在"));
        }
    } catch (error) {
        console.error("加载配置出错:", error);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}


// 初始化WebSocket连接
function initWebSocket(filename = activeConfigName) {
    if (ws) ws.close(); // 先关闭旧连接
    if (reconnectInterval) clearInterval(reconnectInterval);
    
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUri = `${wsProtocol}//${window.location.host}/ws?task=${encodeURIComponent(filename)}`;
    
    addToLog(`尝试连接到WebSocket: ${wsUri}`, 'websocket');
    
    ws = new WebSocket(wsUri);
    
    ws.onopen = function() {
        addToLog('WebSocket连接已建立', 'websocket');
        statusDiv.textContent = '已连接';
        statusDiv.style.backgroundColor = '#e8f5e9';
        statusDiv.style.color = '#198754';
    };
    
    ws.onclose = function(event) {
        addToLog(`WebSocket连接已关闭 (代码: ${event.code}), 正在重连...`, 'websocket');
        statusDiv.textContent = '连接已断开，正在重连...';
        statusDiv.style.backgroundColor = '#fff3cd';
        statusDiv.style.color = '#fd7e14';
        
        // 指数退避重连策略
        let delay = 1000;
        reconnectInterval = setInterval(() => {
            if (ws.readyState === WebSocket.CLOSED) {
                addToLog(`尝试重连 (延迟: ${delay}ms)`, 'websocket');
                initWebSocket();
                delay = Math.min(delay * 2, 10000);
            } else {
                clearInterval(reconnectInterval);
            }
        }, delay);
    };
    
    ws.onerror = function(error) {
        addToLog(`WebSocket错误: ${error}`, 'error');
        statusDiv.textContent = `连接错误`;
        statusDiv.style.backgroundColor = '#f8d7da';
        statusDiv.style.color = '#dc3545';
    };
    
    // 处理接收到的消息
    ws.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            addToLog(data.content || data.message, data.type);
            
            // 解析消息中的系统状态数据并更新
            if (data.type === 'status_update') {
                if (data.iteration) {
                    document.getElementById('current-iteration').textContent = data.iteration;
                }
            }
        } catch (e) {
            addToLog(event.data, 'message');
        }
    };
}

// 添加日志到页面
function addToLog(message, type = 'info') {
    try {
        const now = new Date();
        const timestamp = now.toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            fractionalSecondDigits: 3
        });
        
        const logEntry = document.createElement('div');
        logEntry.className = `log-entry ${type}`;
        
        const timeSpan = document.createElement('span');
        timeSpan.className = 'timestamp';
        timeSpan.textContent = `[${timestamp}]`;
        
        const messageSpan = document.createElement('span');
        messageSpan.textContent = message;
        
        logEntry.appendChild(timeSpan);
        logEntry.appendChild(messageSpan);
        logDiv.appendChild(logEntry);
        
        logDiv.scrollTop = logDiv.scrollHeight;
    } catch (e) {
        console.error('添加日志失败:', e);
    }
}

// 更新状态显示
function updateStatusDisplay(running, paused, statusTextContent) {
    const statusIndicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');
    const runtime = document.getElementById('runtime');
    
    if (statusText) statusText.textContent = statusTextContent;
    if (statusIndicator) {
        statusIndicator.className = 'status-indicator';
        
        if (running) {
            if (paused) {
                statusIndicator.classList.add('status-paused');
                btnPause.innerHTML = '<i class="fas fa-play"></i> 继续';
                // 暂停时停止运行时间计时
                if (runtimeInterval) {
                    clearInterval(runtimeInterval);
                    runtimeInterval = null;
                }
            } else {
                statusIndicator.classList.add('status-running');
                btnPause.innerHTML = '<i class="fas fa-pause"></i> 暂停';
                // 开始或恢复运行时间计时
                if (!runtimeInterval) {
                    if (!startTime) startTime = new Date();
                    updateRuntime();
                    runtimeInterval = setInterval(updateRuntime, 1000);
                }
            }
        } else {
            statusIndicator.classList.add('status-stopped');
            // 停止时重置运行时间
            if (runtimeInterval) {
                clearInterval(runtimeInterval);
                runtimeInterval = null;
            }
            startTime = null;
            if (runtime) runtime.textContent = '00:00:00';
        }
    }
}

// 更新运行时间显示
function updateRuntime() {
    if (!startTime) return;
    
    const now = new Date();
    const elapsedSeconds = Math.floor((now - startTime) / 1000);
    
    const hours = Math.floor(elapsedSeconds / 3600).toString().padStart(2, '0');
    const minutes = Math.floor((elapsedSeconds % 3600) / 60).toString().padStart(2, '0');
    const seconds = (elapsedSeconds % 60).toString().padStart(2, '0');
    
    const runtime = document.getElementById('runtime');
    if (runtime) runtime.textContent = `${hours}:${minutes}:${seconds}`;
}

// 状态更新处理
function startStatusUpdates() {
    if (statusCheckInterval) clearInterval(statusCheckInterval);
    
    async function updateStatus() {
        try {
            const response = await fetch('/status');
            if (!response.ok) {
                throw new Error(`HTTP错误: ${response.status}`);
            }
            const data = await response.json();
            
            // 更新主状态指示器
            updateStatusDisplay(data.running, data.paused, data.status_text);
            
            // 更新控制台状态
            statusDiv.textContent = data.status_text;
            
            // 更新按钮状态
            btnStart.disabled = data.running;
            btnPause.disabled = !data.running;
            btnStop.disabled = !data.running;
            
            // 更新控制台状态样式
            if (data.running) {
                if (data.paused) {
                    statusDiv.style.backgroundColor = '#fff3cd';
                    statusDiv.style.color = '#fd7e14';
                } else {
                    statusDiv.style.backgroundColor = '#e8f5e9';
                    statusDiv.style.color = '#198754';
                }
            } else {
                statusDiv.style.backgroundColor = '#f8f9fa';
                statusDiv.style.color = '#212529';
            }
        } catch (e) {
            addToLog(`获取状态失败: ${e}`, 'error');
            console.error('获取状态失败:', e);
        }
    }
    
    updateStatus();
    statusCheckInterval = setInterval(updateStatus, 1000);
}

// 开始按钮点击事件
async function doStart() {
    // addToLog(`in doStart`, 'info');
    try {
        const configRes = await fetch(`/get_config_status?filename=${encodeURIComponent(activeConfigName)}`);
        const configData = await configRes.json();
        addToLog(`正在请求启动任务: ${activeConfigName}...`, 'status-update');
        const response = await fetch(`/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: "guest",
                configname: activeConfigName.replace('.json', ''),
                // config: configData  // 将完整配置发送过去
            })
        });
        const result = await response.json();
        if (response.ok && result.status === "success") {
            addToLog("任务启动成功", 'info');
        } else {
            throw new Error(result.message || "启动失败");
        }
    } catch (e) {
        addToLog(`开始请求失败: ${e}`, 'error');
    }
}

// 暂停/继续按钮点击事件
async function togglePause() {
    try {
        addToLog('发送暂停/继续请求...', 'status-update');
        const response = await fetch('/pause', { method: 'POST' });
        if (!response.ok) {
            throw new Error(`暂停/继续请求失败: ${response.status}`);
        }
        addToLog('已发送暂停/继续请求', 'status-update');
    } catch (e) {
        addToLog(`暂停/继续请求失败: ${e}`, 'error');
    }
}

// 停止按钮点击事件
async function doStop() {
    try {
        addToLog('发送停止请求...', 'status-update');
        const response = await fetch('/stop', { method: 'POST' });
        if (!response.ok) {
            throw new Error(`停止请求失败: ${response.status}`);
        }
        addToLog('已发送停止请求', 'status-update');
    } catch (e) {
        addToLog(`停止请求失败: ${e}`, 'error');
    }
}

// // 重新载入input.json按钮点击事件
// async function reloadInputJson() {
//     try {
//         // 禁用按钮并显示加载状态
//         btnReloadInput.disabled = true;
//         btnReloadInput.innerHTML = '<i class="fas fa-spinner fa-spin"></i> loading...';
        
//         addToLog('reloading config...', 'status-update');

//         const response = await fetch('/reset', { method: 'POST' });
//         if (!response.ok) {
//             throw new Error(`request error: ${response.status}`);
//         }
        
//         // 调用已有的系统状态获取函数，该函数会重新读取input.json
//         fetchSystemStatus();
        
//         addToLog('config reload success', 'status-update');
//     } catch (e) {
//         addToLog(`config reload dail: ${e}`, 'error');
//     } finally {
//         // 恢复按钮状态
//         btnReloadInput.disabled = false;
//         btnReloadInput.innerHTML = '<i class="fas fa-file-import"></i>  <span data-i18n="index.btn_reload">Reload input.json</span>';
//     }
// }

// 获取操作状态的文本描述
function getOperationText(operationCode) {
    const operationMap = {
        '0': '生成查询点',
        '1': '等待DFT计算',
        '2': '模型训练'
    };
    return operationMap[operationCode] || `未知操作 (${operationCode})`;
}

// 获取操作状态的CSS类
function getOperationClass(operationCode) {
    return operationCode ? `operation-${operationCode}` : 'operation-unknown';
}

// 重置加载状态
function resetLoadingState() {
    const loadingElements = [
        'phase-name', 
        'current-iteration', 
        'current-operation-number'
    ];
    
    loadingElements.forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.innerHTML = '<span class="loading-spinner"></span>加载中...';
        }
    });
    
    const operationText = document.getElementById('current-operation-text');
    if (operationText) {
        operationText.className = 'operation-status operation-unknown';
        operationText.textContent = '未知';
    }
}

// 通过后端接口读取本地record.txt文件
async function readRecordFile() {
    if (!recordPath) {
        addToLog('未获取到record_path，无法读取记录文件', 'warning');
        document.getElementById('current-iteration').textContent = '无法获取';
        document.getElementById('current-operation-number').textContent = '无法获取';
        return;
    }
    
    try {
        // 设置超时
        const abortController = new AbortController();
        const timeoutId = setTimeout(() => abortController.abort(), 10000); // 10秒超时
        
        addToLog(`尝试读取本地记录文件: ${recordPath}`, 'info');
        
        // 发送文件路径到后端，由后端读取文件内容
        const response = await fetch('/read-record', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ file_path: recordPath }),
            signal: abortController.signal
        });
        
        clearTimeout(timeoutId);
        
        if (!response.ok) {
            if (response.status === 404) {
                addToLog(`记录文件不存在: ${recordPath}`, 'warning');
                document.getElementById('current-iteration').textContent = '文件不存在';
                document.getElementById('current-operation-number').textContent = '文件不存在';
            } else {
                addToLog(`读取记录文件失败: HTTP状态码 ${response.status}`, 'error');
                document.getElementById('current-iteration').textContent = '读取失败';
                document.getElementById('current-operation-number').textContent = '读取失败';
            }
            return;
        }
        
        const result = await response.json();
        
        if (!result.success) {
            addToLog(`读取记录文件失败: ${result.error || '未知错误'}`, 'error');
            document.getElementById('current-iteration').textContent = '读取失败';
            document.getElementById('current-operation-number').textContent = '读取失败';
            return;
        }
        
        // 分割成行并过滤空行
        const lines = result.content.split('\n')
            .map(line => line.trim())
            .filter(line => line.length > 0);
        
        if (lines.length === 0) {
            addToLog('记录文件为空', 'info');
            document.getElementById('current-iteration').textContent = '无数据';
            document.getElementById('current-operation-number').textContent = '无数据';
            return;
        }
        
        // 获取最后一行
        const lastLine = lines[lines.length - 1];
        // 分割成两个数字
        const [iteration, operation] = lastLine.split(/\s+/).map(num => num.trim());
        
        if (iteration && operation) {
            // 更新UI显示
            document.getElementById('current-iteration').textContent = iteration;
            document.getElementById('current-operation-number').textContent = operation;
            
            const operationTextEl = document.getElementById('current-operation-text');
            operationTextEl.textContent = getOperationText(operation);
            // 移除旧的操作类并添加新的
            operationTextEl.className = '';
            operationTextEl.classList.add('operation-status', getOperationClass(operation));
            
            addToLog(`已更新迭代信息: 第 ${iteration} 代, 操作 ${operation} (${getOperationText(operation)})`, 'status-update');
        } else {
            addToLog(`记录文件最后一行格式不正确: "${lastLine}"`, 'error');
            document.getElementById('current-iteration').textContent = '格式错误';
            document.getElementById('current-operation-number').textContent = '格式错误';
        }
    } catch (error) {
        if (error.name === 'AbortError') {
            addToLog('读取记录文件超时', 'error');
        } else {
            addToLog(`读取记录文件时发生错误: ${error.message}`, 'error');
        }
        console.error('读取记录文件错误:', error);
        document.getElementById('current-iteration').textContent = '加载失败';
        document.getElementById('current-operation-number').textContent = '加载失败';
    }
}

// 页面关闭时清理
window.onbeforeunload = function() {
    if (ws) {
        ws.close(1000, "页面关闭");
    }
    if (reconnectInterval) clearInterval(reconnectInterval);
    if (statusCheckInterval) clearInterval(statusCheckInterval);
    if (runtimeInterval) clearInterval(runtimeInterval);
    if (fetchTimeout) clearTimeout(fetchTimeout);
};

// // 读取并显示系统状态数据的函数
// function fetchSystemStatus() {
//     // 重置加载状态
//     resetLoadingState();
    
//     // 定义需要操作的元素ID和对应的数据路径
//     const statusMappings = [
//         { id: 'phase-name', path: 'phase_name', defaultValue: '未设置' },
//         { id: 'ml-model', path: 'AL_set.ML_model', defaultValue: '未设置' }
//     ];

//     // 检查所有必要元素是否存在
//     const missingElements = statusMappings.filter(item => !document.getElementById(item.id));
//     if (missingElements.length > 0) {
//         console.error('缺少必要的DOM元素:', missingElements.map(item => item.id));
//         return;
//     }

//     // 清除之前的超时
//     if (fetchTimeout) clearTimeout(fetchTimeout);
    
//     // 设置超时
//     const abortController = new AbortController();
//     fetchTimeout = setTimeout(() => abortController.abort(), 10000); // 10秒超时
    
//     fetch(`/get_config_status?filename=${encodeURIComponent(filename)}`)
//         .then(response => {
//             clearTimeout(fetchTimeout);
//             if (!response.ok) {
//                 throw new Error(`HTTP错误，状态码: ${response.status}`);
//             }
//             return response.json();
//         })
//         .then(data => {
//             console.log('成功获取系统状态数据:', data);
            
//             // 逐个设置每个状态值
//             statusMappings.forEach(item => {
//                 // 按路径获取值
//                 const value = item.path.split('.').reduce((obj, key) => {
//                     return obj && obj[key] !== undefined ? obj[key] : undefined;
//                 }, data);
                
//                 // 设置值，使用默认值
//                 const element = document.getElementById(item.id);
//                 if (element) {
//                     element.textContent = value !== undefined ? value : item.defaultValue;
//                 }
//             });
            
//             // 保存record_path（文件系统路径）并读取记录文件
//             if (data.record_path) {
//                 // 拼接完整的record.txt文件路径
//                 recordPath = data.record_path + '/record.txt';
//                 addToLog(`获取到本地文件路径: ${recordPath}`, 'info');
//                 // 读取记录文件（通过后端接口）
//                 readRecordFile();
//             } else {
//                 addToLog('未在input.json中找到record_path', 'warning');
//                 recordPath = null;
//                 document.getElementById('current-iteration').textContent = '无路径';
//                 document.getElementById('current-operation-number').textContent = '无路径';
//             }
//         })
//         .catch(error => {
//             clearTimeout(fetchTimeout);
            
//             console.error('获取系统状态失败:', error);
            
//             // 显示具体错误而不是一直加载中
//             statusMappings.forEach(item => {
//                 const element = document.getElementById(item.id);
//                 if (element) {
//                     if (error.name === 'AbortError') {
//                         element.textContent = '加载超时';
//                     } else {
//                         element.textContent = '获取失败';
//                     }
//                 }
//             });
            
//             // 更新迭代相关状态
//             document.getElementById('current-iteration').textContent = '获取失败';
//             document.getElementById('current-operation-number').textContent = '获取失败';
//         });
// }

// --- 生命周期控制 ---
let statusTimer = null;

function startGlobalMonitoring() {
    // 清理旧定时器
    if (statusTimer) clearInterval(statusTimer);

    // 1. 立即执行一次
    fetchSystemStatus(activeConfigName);
    initWebSocket(activeConfigName);

    // 2. 设置定时轮询
    statusTimer = setInterval(() => {
        fetchSystemStatus(activeConfigName);
    }, 5000);
}

window.onload = function() {
    // 自动从 URL 获取任务名（例如 index.html?task=A.json）
    const urlParams = new URLSearchParams(window.location.search);
    const taskFromUrl = urlParams.get('task');
    if (taskFromUrl) {
        activeConfigName = taskFromUrl;
        const input = document.getElementById('target-config-file');
        if (input) input.value = taskFromUrl;
    }
    
    startGlobalMonitoring();
};

window.onbeforeunload = () => {
    if (ws) ws.close();
};