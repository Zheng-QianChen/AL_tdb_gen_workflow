
// 定义变量
let itermax = 0;  // 当前迭代变量
let process = 0;  // 当前操作变量
let phaseName = ""; // 相名称

// 图片基础路径
const IMAGE_BASE_PATH = '/static/fig/';

// 图片缓存 - 使用localStorage存储图片数据
const IMAGE_CACHE = "al_visualization_image_cache";

// 数据缓存
const DATA_CACHE = "al_visualization_data_cache";

// 其他迭代数据变量
let totalIterations = 0;
let currentIteration = 1;
let recordPath = null;
let csvPath = null; // iter.csv路径
let csvData = []; // 存储解析后的CSV数据
let csvRawContent = ""; // 存储原始CSV内容用于错误诊断

// 预测图片的迭代范围
let predImageMinIter = 1;
let predImageMaxIter = 0;
let currentPredIter1 = 1;  // 第二张图：默认iter0001
let currentPredIter2 = 1;  // 第三张图：默认itermax

// 初始化函数
function initDataFetch() {
    // 重置加载状态
    resetLoadingState();
    
    // 初始化缓存
    initImageCache();
    initDataCache();
    
    // 首次加载数据
    fetchSystemStatus();
    
    // 设置定时器定期同步数据（每3秒）
    setInterval(() => {
        fetchSystemStatus();
    }, 3000);
    
    // 绑定错误详情显示按钮事件
    document.getElementById('show-error-details').addEventListener('click', function() {
        const detailsElement = document.getElementById('csv-error-details');
        if (detailsElement.style.display === 'none' || detailsElement.style.display === '') {
            detailsElement.style.display = 'block';
            this.textContent = '隐藏详情';
        } else {
            detailsElement.style.display = 'none';
            this.textContent = '显示详情';
        }
    });
    
    // 绑定强制刷新按钮事件
    document.getElementById('force-refresh-main').addEventListener('click', function() {
        // 清除缓存中该图片的记录
        const formattedIter = String(currentIteration).padStart(4, '0');
        const baseImageUrl = `${IMAGE_BASE_PATH}iter.png`;
        
        try {
            const cache = JSON.parse(localStorage.getItem(IMAGE_CACHE) || '{}');
            if (cache[baseImageUrl]) {
                delete cache[baseImageUrl];
                localStorage.setItem(IMAGE_CACHE, JSON.stringify(cache));
                console.log('已清除综合指标图缓存');
            }
        } catch (e) {
            console.error('清除缓存失败:', e);
        }
        
        // 显示刷新中状态
        this.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 刷新中...';
        this.disabled = true;
        
        // 重新加载图片
        updateMainImage().then(() => {
            // 恢复按钮状态
            this.innerHTML = '<i class="fas fa-sync-alt"></i> 强制刷新综合指标图';
            this.disabled = false;
        }).catch(() => {
            // 即使失败也恢复按钮状态
            this.innerHTML = '<i class="fas fa-sync-alt"></i> 强制刷新综合指标图';
            this.disabled = false;
        });
    });
}

// 初始化图片缓存
function initImageCache() {
    if (!localStorage.getItem(IMAGE_CACHE)) {
        localStorage.setItem(IMAGE_CACHE, JSON.stringify({}));
    }
}

// 初始化数据缓存
function initDataCache() {
    if (!localStorage.getItem(DATA_CACHE)) {
        localStorage.setItem(DATA_CACHE, JSON.stringify({}));
    }
}

// 从缓存获取图片
function getImageFromCache(url) {
    try {
        const cache = JSON.parse(localStorage.getItem(IMAGE_CACHE) || '{}');
        return cache[url] || null;
    } catch (e) {
        console.error('获取图片缓存失败:', e);
        return null;
    }
}

// 将图片存入缓存
function saveImageToCache(url, dataUrl) {
    try {
        const cache = JSON.parse(localStorage.getItem(IMAGE_CACHE) || '{}');
        // 限制缓存大小，只保留最近的20张图片
        const cacheEntries = Object.entries(cache);
        if (cacheEntries.length >= 20) {
            // 删除最早的缓存
            const oldestKey = cacheEntries[0][0];
            delete cache[oldestKey];
        }
        cache[url] = {
            data: dataUrl,
            timestamp: new Date().getTime()
        };
        localStorage.setItem(IMAGE_CACHE, JSON.stringify(cache));
    } catch (e) {
        console.error('保存图片缓存失败:', e);
    }
}

// 从缓存获取数据
function getDataFromCache(path) {
    try {
        const cache = JSON.parse(localStorage.getItem(DATA_CACHE) || '{}');
        return cache[path] || null;
    } catch (e) {
        console.error('获取数据缓存失败:', e);
        return null;
    }
}

// 保存数据到缓存
function saveDataToCache(path, data) {
    try {
        const cache = JSON.parse(localStorage.getItem(DATA_CACHE) || '{}');
        cache[path] = {
            data: data,
            timestamp: new Date().getTime()
        };
        localStorage.setItem(DATA_CACHE, JSON.stringify(cache));
    } catch (e) {
        console.error('保存数据缓存失败:', e);
    }
}

// 重置加载状态
function resetLoadingState() {
    const loadingElements = [
        'phase-name', 'current-iteration', 'current-operation-number',
        'ml-model', 'current-iter', 'total-iters',
        'data-count', 'train-rmse', 'test-rmse', 'cv-info', 'r2-score',
        'pred-range-1', 'pred-range-2', 'pred-r2-1', 'pred-r2-2'
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
    
    // 隐藏错误信息
    document.getElementById('data-error').style.display = 'none';
    document.getElementById('csv-error-details').style.display = 'none';
}

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
    return operationCode ? `operation-status operation-${operationCode}` : 'operation-status operation-unknown';
}

// 从后端API获取系统状态
function fetchSystemStatus() {
    // 定义需要操作的元素ID和对应的数据路径
    const statusMappings = [
        { id: 'phase-name', path: 'phase_name', defaultValue: '未设置' },
        { id: 'ml-model', path: 'AL_set.ML_model', defaultValue: '未设置' }
    ];

    // 设置超时
    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), 10000); // 10秒超时
    
    fetch('/static/run/input.json', { signal: abortController.signal })
        .then(response => {
            clearTimeout(timeoutId);
            
            if (!response.ok) {
                throw new Error(`HTTP错误，状态码: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('成功获取系统状态数据:', data);
            
            // 逐个设置每个状态值
            statusMappings.forEach(item => {
                // 按路径获取值
                const value = item.path.split('.').reduce((obj, key) => {
                    return obj && obj[key] !== undefined ? obj[key] : undefined;
                }, data);
                
                // 设置值，使用默认值
                const element = document.getElementById(item.id);
                if (element) {
                    element.textContent = value !== undefined ? value : item.defaultValue;
                    
                    // 保存相名称
                    if (item.id === 'phase-name' && value) {
                        phaseName = value;
                    }
                }
            });
            
            // 保存record_path并读取记录文件和CSV数据
            if (data.record_path) {
                recordPath = data.record_path + '/record.txt';
                csvPath = data.record_path + '/iter.csv'; // iter.csv与record.txt同目录
                readRecordFile();
                readCsvFile(); // 读取CSV文件
            } else {
                console.log('未在input.json中找到record_path');
                document.getElementById('current-iteration').textContent = '无路径';
                document.getElementById('current-operation-number').textContent = '无路径';
            }
        })
        .catch(error => {
            clearTimeout(timeoutId);
            console.error('获取系统状态失败:', error);
            
            // 显示错误信息
            if (error.name === 'AbortError') {
                document.getElementById('phase-name').textContent = '加载超时';
                document.getElementById('ml-model').textContent = '加载超时';
            } else {
                document.getElementById('phase-name').textContent = '获取失败';
                document.getElementById('ml-model').textContent = '获取失败';
            }
        });
}

// 读取记录文件获取迭代信息
function readRecordFile() {
    if (!recordPath) {
        console.log('未获取到record_path，无法读取记录文件');
        return;
    }
    
    try {
        // 设置超时
        const abortController = new AbortController();
        const timeoutId = setTimeout(() => abortController.abort(), 10000);
        
        // 发送文件路径到后端，由后端读取文件内容
        fetch('/read-record', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ file_path: recordPath }),
            signal: abortController.signal
        })
        .then(response => {
            clearTimeout(timeoutId);
            
            if (!response.ok) {
                throw new Error(`HTTP状态码: ${response.status}`);
            }
            return response.json();
        })
        .then(result => {
            if (!result.success) {
                throw new Error(result.error || '未知错误');
            }
            
            // 分割成行并过滤空行
            const lines = result.content.split('\n')
                .map(line => line.trim())
                .filter(line => line.length > 0);
            
            if (lines.length === 0) {
                console.log('记录文件为空');
                document.getElementById('current-iteration').textContent = '无数据';
                document.getElementById('current-operation-number').textContent = '无数据';
                return;
            }
            
            // 获取最后一行
            const lastLine = lines[lines.length - 1];
            // 分割成两个数字
            const [iteration, operation] = lastLine.split(/\s+/).map(num => num.trim());
            
            if (iteration && operation) {
                // 更新变量
                let Itermax = parseInt(iteration);
                process = operation;
                
                // 根据process调整itermax
                if (process != 2) {
                    newItermax = Math.max(1, Itermax - 1);
                }
                
                // 更新UI显示
                document.getElementById('current-iteration').textContent = Itermax;
                document.getElementById('current-operation-number').textContent = process;
                
                const operationTextEl = document.getElementById('current-operation-text');
                operationTextEl.textContent = getOperationText(process);
                operationTextEl.className = getOperationClass(process);
                
                // 如果是新的迭代，更新当前迭代
                if (newItermax !== itermax) {
                    itermax = newItermax;
                    currentIteration = itermax;
                    
                    // 设置总迭代数等于itermax
                    totalIterations = itermax;
                    predImageMaxIter = totalIterations;
                    
                    // 更新第三张图为最新迭代
                    currentPredIter2 = itermax;
                    
                    updateIterationDisplay();
                    updateAllImages();
                    updateMetricsFromCsv(); // 从CSV更新指标
                }
            } else {
                console.log(`记录文件最后一行格式不正确: "${lastLine}"`);
                document.getElementById('current-iteration').textContent = '格式错误';
                document.getElementById('current-operation-number').textContent = '格式错误';
            }
        })
        .catch(error => {
            clearTimeout(timeoutId);
            console.error('读取记录文件错误:', error);
            
            if (error.name === 'AbortError') {
                document.getElementById('current-iteration').textContent = '读取超时';
                document.getElementById('current-operation-number').textContent = '读取超时';
            } else {
                document.getElementById('current-iteration').textContent = '读取失败';
                document.getElementById('current-operation-number').textContent = '读取失败';
            }
        });
    } catch (error) {
        console.error('读取记录文件时发生错误:', error);
        document.getElementById('current-iteration').textContent = '加载失败';
        document.getElementById('current-operation-number').textContent = '加载失败';
    }
}

// 修改readCsvFile函数，增加错误处理和调试信息
function readCsvFile() {
    if (!csvPath) {
        console.log('未获取到csvPath，无法读取CSV文件');
        showDataError('未找到iter.csv文件路径');
        return;
    }
    
    // 打印调试信息，确认请求的路径
    console.log('尝试读取CSV文件:', csvPath);
    
    try {
        const abortController = new AbortController();
        const timeoutId = setTimeout(() => abortController.abort(), 10000);
        
        fetch('/read-record', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ file_path: csvPath }),
            signal: abortController.signal
        })
        .then(response => {
            clearTimeout(timeoutId);
            
            // 打印HTTP响应状态
            console.log('CSV文件请求响应状态:', response.status);
            
            if (!response.ok) {
                throw new Error(`HTTP状态码: ${response.status}`);
            }
            return response.json();
        })
        .then(result => {
            // 提取CSV字符串内容
            const content = result.content;
            
            // 打印原始内容预览，帮助调试
            console.log('CSV文件内容预览:', content.substring(0, 200) + (content.length > 200 ? '...' : ''));
            
            csvRawContent = content;
            csvData = parseCsvContent(content);
            saveDataToCache(csvPath, csvData);
            updateMetricsFromCsv();
            console.log(`成功解析CSV数据，共${csvData.length}条记录`);
        })
        .catch(error => {
            clearTimeout(timeoutId);
            console.error('读取CSV文件错误:', error);
            
            // 更详细的错误信息
            let errorMsg, errorDetails;
            if (error.name === 'AbortError') {
                errorMsg = 'CSV文件读取超时';
                errorDetails = `超时错误: 读取文件 ${csvPath} 超过10秒未响应`;
            } else {
                errorMsg = `CSV文件读取失败: ${error.message}`;
                errorDetails = `错误详情: ${error.stack}\n文件路径: ${csvPath}`;
            }
            
            showDataError(errorMsg, errorDetails);
        });
    } catch (error) {
        console.error('读取CSV文件时发生错误:', error);
        showDataError(`处理CSV时出错: ${error.message}`, 
            `错误详情: ${error.stack}\n文件路径: ${csvPath}`);
    }
}


// 修改CSV解析函数，放宽格式要求
function parseCsvContent(content) {
    const data = [];
    let errorDetails = [];
    
    if (!content.trim()) {
        errorDetails.push("CSV文件内容为空");
        showDataError("CSV文件内容为空", errorDetails.join("\n"));
        return data;
    }
    
    // 分割行并过滤空行
    const lines = content.split('\n')
        .map((line, index) => ({ line: line.trim(), row: index + 1 }))
        .filter(item => item.line.length > 0);
    
    if (lines.length < 2) {
        errorDetails.push(`CSV文件内容不足，至少需要标题行和一行数据，实际只有${lines.length}行`);
        showDataError("CSV文件格式错误", errorDetails.join("\n"));
        return data;
    }
    
    // 解析标题行
    const headerLine = lines[0];
    const headers = headerLine.line.split(',').map(header => header.trim());
    
    // 打印标题行信息用于调试
    console.log(`CSV标题行: ${headers.length}列 -`, headers);
    
    // 放宽列数检查，只警告不阻断
    if (headers.length !== 7) {
        errorDetails.push(`警告: 标题行格式不符合预期，预期7列，实际${headers.length}列`);
        errorDetails.push(`标题行内容: "${headerLine.line}"`);
    }
    
    // 解析数据行
    for (let i = 1; i < lines.length; i++) {
        const lineItem = lines[i];
        const values = lineItem.line.split(',').map(value => value.trim());
        
        // 同样放宽列数检查
        if (values.length !== 7) {
            errorDetails.push(`警告: 行 ${lineItem.row} 列数不符合预期: 预期7列，实际${values.length}列`);
            // 不跳过，尝试解析可用数据
        }
        
        try {
            // 更健壮的解析逻辑，处理可能的缺失值
            const record = {
                iteration: i,
                trainingDataAmount: values[0] ? parseInt(values[0]) : null,
                rmseTrain: values[1] ? parseFloat(values[1]) : null,
                rmseTest: values[2] ? parseFloat(values[2]) : null,
                foldNumR2: values[3] ? parseInt(values[3]) : null,
                r2Score: values[4] ? parseFloat(values[4]) : null,
                foldNumRMSE: values[5] ? parseInt(values[5]) : null,
                rmseScore: values[6] ? parseFloat(values[6]) : null
            };
            
            // 允许部分字段为空，但至少需要有部分有效数据
            const hasValidData = Object.values(record).some(v => v !== null && !isNaN(v));
            if (hasValidData) {
                data.push(record);
            } else {
                errorDetails.push(`行 ${lineItem.row} 没有有效数据: "${lineItem.line}"`);
            }
        } catch (error) {
            errorDetails.push(`解析行 ${lineItem.row} 时出错: ${error.message}`);
            errorDetails.push(`行内容: "${lineItem.line}"`);
        }
    }
    
    // 即使有错误，只要有数据就使用
    if (data.length > 0) {
        if (errorDetails.length > 0) {
            showDataError(`CSV文件解析有${errorDetails.length}个警告，但已成功解析${data.length}条有效记录`, 
                errorDetails.join("\n\n") + "\n\n将使用可用数据继续运行");
        }
        return data;
    } else {
        errorDetails.push("未解析到任何有效数据记录");
        showDataError("未找到有效的CSV数据", errorDetails.join("\n"));
        return [];
    }
}

// 从CSV更新指标显示
function updateMetricsFromCsv() {
    if (csvData.length === 0) {
        showDataError('未找到有效的CSV数据', 
            `CSV文件路径: ${csvPath}\n` +
            `原始内容预览: ${csvRawContent.substring(0, 500)}${csvRawContent.length > 500 ? '...' : ''}`);
        return;
    }
    
    // 根据当前迭代查找数据
    let csvRecord = null;
    
    // 找到与当前迭代匹配的记录
    if (currentIteration && !isNaN(currentIteration)) {
        // 迭代从1开始，数组索引从0开始
        const index = Math.min(currentIteration - 1, csvData.length - 1);
        if (index >= 0) {
            csvRecord = csvData[index];
        }
    }
    
    // 如果没有找到，使用最后一条记录
    if (!csvRecord && csvData.length > 0) {
        csvRecord = csvData[csvData.length - 1];
    }
    
    // 更新显示
    if (csvRecord) {
        document.getElementById('data-count').textContent = csvRecord.trainingDataAmount;
        document.getElementById('train-rmse').textContent = csvRecord.rmseTrain.toFixed(3);
        document.getElementById('test-rmse').textContent = csvRecord.rmseTest.toFixed(3);
        document.getElementById('cv-info').textContent = `${csvRecord.foldNumRMSE}折: ${csvRecord.rmseScore.toFixed(3)}`;
        document.getElementById('r2-score').textContent = csvRecord.r2Score.toFixed(3);
        
        // 更新预测图的R²值
        document.getElementById('pred-r2-1').textContent = `R²: ${csvRecord.r2Score.toFixed(3)}`;
        document.getElementById('pred-r2-2').textContent = `R²: ${csvRecord.r2Score.toFixed(3)}`;
    } else {
        document.getElementById('data-count').textContent = 'N/A';
        document.getElementById('train-rmse').textContent = 'N/A';
        document.getElementById('test-rmse').textContent = 'N/A';
        document.getElementById('cv-info').textContent = 'N/A';
        document.getElementById('r2-score').textContent = 'N/A';
        document.getElementById('pred-r2-1').textContent = 'R²: N/A';
        document.getElementById('pred-r2-2').textContent = 'R²: N/A';
    }
    
    // 隐藏错误信息
    document.getElementById('data-error').style.display = 'none';
    document.getElementById('csv-error-details').style.display = 'none';
}

// 显示数据错误信息
function showDataError(message, details) {
    const errorElement = document.getElementById('data-error');
    const detailsElement = document.getElementById('csv-error-details');
    
    errorElement.innerHTML = `数据错误: ${message} <button class="btn btn-sm btn-danger show-details-btn" id="show-error-details">显示详情</button>`;
    errorElement.style.display = 'block';
    
    // 格式化详细信息
    if (details) {
        // 替换换行符为HTML换行
        let formattedDetails = details.replace(/\n/g, '<br>');
        // 显示文件路径
        if (csvPath) {
            formattedDetails = `文件路径: ${csvPath}<br><br>${formattedDetails}`;
        }
        detailsElement.innerHTML = formattedDetails;
    } else {
        detailsElement.innerHTML = `文件路径: ${csvPath}<br>未提供详细错误信息`;
    }
    
    // 自动隐藏详情
    detailsElement.style.display = 'none';
}

// 更新迭代显示
function updateIterationDisplay() {
    document.getElementById('current-iter').textContent = currentIteration;
    document.getElementById('iter-pred-1').value = currentPredIter1;
    document.getElementById('iter-pred-2').value = currentPredIter2;
    document.getElementById('total-iters').textContent = itermax;
    document.getElementById('pred-range-1').textContent = `1 - ${predImageMaxIter}`;
    document.getElementById('pred-range-2').textContent = `1 - ${predImageMaxIter}`;
}

// 更新所有图片
function updateAllImages() {
    // 使用Promise确保图片加载状态可控
    updateMainImage()
        .then(() => console.log('主图加载完成'))
        .catch(err => console.error('主图加载失败:', err));
        
    updatePredImage(1, currentPredIter1)
        .then(() => console.log('预测图1加载完成'))
        .catch(err => console.error('预测图1加载失败:', err));
        
    updatePredImage(2, currentPredIter2)
        .then(() => console.log('预测图2加载完成'))
        .catch(err => console.error('预测图2加载失败:', err));
        
    updateOtherTabImages(currentIteration);
}

// 更新主图片 - 使用缓存机制
function updateMainImage() {
    return new Promise((resolve, reject) => {
        if (!phaseName) {
            reject(new Error('未获取到相名称'));
            return;
        }
        
        // 显示加载状态
        const loadingElement = document.getElementById('main-loading');
        const imageElement = document.getElementById('main-image');
        const pathElement = document.getElementById('main-image-path');
        const statusElement = document.getElementById('main-image-status');
        const cacheIndicator = document.getElementById('main-image-cache');
        
        loadingElement.style.display = 'block';
        imageElement.style.display = 'none';
        statusElement.style.display = 'block';
        statusElement.textContent = '加载中...';
        cacheIndicator.style.display = 'none';
        
        // 构建图片URL，包含相名称
        const formattedIter = String(currentIteration).padStart(4, '0');
        const baseImageUrl = `${IMAGE_BASE_PATH}iter.png`;
        
        // 检查缓存
        const cachedImage = getImageFromCache(baseImageUrl);
        if (cachedImage) {
            // 使用缓存图片
            imageElement.src = cachedImage.data;
            loadingElement.style.display = 'none';
            imageElement.style.display = 'block';
            statusElement.textContent = '加载完成';
            cacheIndicator.style.display = 'block';
            pathElement.textContent = `图片路径: ${baseImageUrl} (已缓存)`;
            console.log('使用缓存加载主图:', baseImageUrl);
            resolve();
            return;
        }
        
        // 添加时间戳避免缓存
        const timestamp = new Date().getTime();
        const imageUrl = `${baseImageUrl}?timestamp=${timestamp}`;
        
        // 显示图片路径
        pathElement.textContent = `图片路径: ${baseImageUrl}`;
        
        // 清除之前的事件监听
        imageElement.onload = null;
        imageElement.onerror = null;
        
        // 清除之前的图片源，确保重新加载
        imageElement.src = '';
        
        // 创建图片对象用于预加载
        const img = new Image();
        
        // 设置超时时间为20秒
        const timeout = setTimeout(() => {
            statusElement.textContent = '加载超时，重试中...';
            
            // 第一次超时后尝试重新加载
            img.src = '';
            setTimeout(() => {
                const newTimestamp = new Date().getTime();
                img.src = `${baseImageUrl}?timestamp=${newTimestamp}`;
            }, 1000);
            
            // 第二次超时则显示错误
            const secondTimeout = setTimeout(() => {
                loadingElement.innerHTML = `
                    <i class="fas fa-exclamation-triangle text-warning fa-3x"></i>
                    <p class="mt-2">图片加载超时</p>
                    <p class="text-muted">请检查网络连接或文件路径</p>
                    <button class="btn btn-sm btn-primary mt-2" onclick="updateMainImage()">重试</button>
                `;
                statusElement.style.display = 'none';
                reject(new Error('图片加载超时'));
            }, 20000);
            
            // 如果第二次加载成功，清除第二次超时
            img.onload = function() {
                clearTimeout(secondTimeout);
                // 转换为dataURL并存入缓存
                const canvas = document.createElement('canvas');
                canvas.width = img.width;
                canvas.height = img.height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                const dataUrl = canvas.toDataURL('image/png');
                saveImageToCache(baseImageUrl, dataUrl);
                
                loadingElement.style.display = 'none';
                imageElement.style.display = 'block';
                imageElement.src = dataUrl;
                statusElement.textContent = '加载完成';
                console.log('综合训练指标视图加载成功（重试后）');
                resolve();
            };
        }, 20000);
        
        // 图片加载成功
        img.onload = function() {
            clearTimeout(timeout);
            
            // 转换为dataURL并存入缓存
            const canvas = document.createElement('canvas');
            canvas.width = img.width;
            canvas.height = img.height;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            const dataUrl = canvas.toDataURL('image/png');
            saveImageToCache(baseImageUrl, dataUrl);
            
            loadingElement.style.display = 'none';
            imageElement.style.display = 'block';
            imageElement.src = dataUrl;
            statusElement.textContent = '加载完成';
            console.log('综合训练指标视图加载成功');
            resolve();
        };
        
        img.onerror = function(error) {
            clearTimeout(timeout);
            console.error('综合训练指标视图加载失败:', error);
            loadingElement.innerHTML = `
                <i class="fas fa-exclamation-triangle text-warning fa-3x"></i>
                <p class="mt-2">图片加载失败</p>
                <p class="text-muted">请检查文件是否存在: ${baseImageUrl}</p>
                <button class="btn btn-sm btn-primary mt-2" onclick="updateMainImage()">重试</button>
            `;
            statusElement.style.display = 'none';
            reject(error);
        };
        
        // 尝试加载图片
        img.src = imageUrl;
    });
}

// 更新预测图片 - 使用缓存机制
function updatePredImage(processNum, iter) {
    return new Promise((resolve, reject) => {
        if (!phaseName) {
            reject(new Error('未获取到相名称'));
            return;
        }
        
        // 确保迭代在有效范围内
        if (iter < predImageMinIter || iter > predImageMaxIter || predImageMaxIter === 0) {
            reject(new Error('迭代值超出有效范围'));
            return;
        }
        
        // 更新当前迭代
        if (processNum === 1) {
            currentPredIter1 = iter;
            document.getElementById('iter-pred-1').value = iter;
        } else {
            currentPredIter2 = iter;
            document.getElementById('iter-pred-2').value = iter;
        }
        
        // 显示加载状态
        const loadingElement = document.getElementById(`pred-loading-${processNum}`);
        const imageElement = document.getElementById(`pred-image-${processNum}`);
        const pathElement = document.getElementById(`pred-image-path-${processNum}`);
        const statusElement = document.getElementById(`pred-image-status-${processNum}`);
        const cacheIndicator = document.getElementById(`pred-image-cache-${processNum}`);
        
        loadingElement.style.display = 'block';
        imageElement.style.display = 'none';
        statusElement.style.display = 'block';
        statusElement.textContent = '加载中...';
        cacheIndicator.style.display = 'none';
        
        // 构建图片URL，包含相名称，process固定为2
        const formattedIter = String(iter).padStart(4, '0');
        const baseImageUrl = `${IMAGE_BASE_PATH}pred_test_${phaseName}_iter${formattedIter}_process2.png`;
        
        // 检查缓存
        const cachedImage = getImageFromCache(baseImageUrl);
        if (cachedImage) {
            // 使用缓存图片
            imageElement.src = cachedImage.data;
            loadingElement.style.display = 'none';
            imageElement.style.display = 'block';
            statusElement.textContent = '加载完成';
            cacheIndicator.style.display = 'block';
            pathElement.textContent = `图片路径: ${baseImageUrl} (已缓存)`;
            console.log(`使用缓存加载预测图${processNum}:`, baseImageUrl);
            
            // 从CSV数据更新R²值
            if (csvData.length > 0) {
                const r2Element = document.getElementById(`pred-r2-${processNum}`);
                // 迭代从1开始，数组索引从0开始
                const index = Math.min(iter - 1, csvData.length - 1);
                let r2Value = null;
                if (index >= 0) {
                    r2Value = csvData[index].r2Score;
                }
                // 如果没有对应的值，使用最后一个
                if (r2Value === null && csvData.length > 0) {
                    r2Value = csvData[csvData.length - 1].r2Score;
                }
                r2Element.textContent = r2Value !== null ? 
                    `R²: ${r2Value.toFixed(3)}` : 'R²: N/A';
            }
            
            resolve();
            return;
        }
        
        // 添加时间戳避免缓存
        const timestamp = new Date().getTime();
        const imageUrl = `${baseImageUrl}?timestamp=${timestamp}`;
        
        // 显示图片路径
        pathElement.textContent = `图片路径: ${baseImageUrl}`;
        
        // 清除之前的事件监听
        imageElement.onload = null;
        imageElement.onerror = null;
        
        // 创建图片对象用于预加载
        const img = new Image();
        
        // 设置超时时间为20秒
        const timeout = setTimeout(() => {
            statusElement.textContent = '加载超时，重试中...';
            
            // 第一次超时后尝试重新加载
            img.src = '';
            setTimeout(() => {
                const newTimestamp = new Date().getTime();
                img.src = `${baseImageUrl}?timestamp=${newTimestamp}`;
            }, 1000);
            
            // 第二次超时则显示错误
            const secondTimeout = setTimeout(() => {
                loadingElement.innerHTML = `
                    <i class="fas fa-exclamation-triangle text-warning fa-3x"></i>
                    <p class="mt-2">图片加载超时</p>
                    <p class="text-muted">请检查文件是否存在: ${baseImageUrl}</p>
                    <button class="btn btn-sm btn-primary mt-2" onclick="updatePredImage(${processNum}, ${iter})">重试</button>
                `;
                statusElement.style.display = 'none';
                reject(new Error('图片加载超时'));
            }, 20000);
            
            // 如果第二次加载成功，清除第二次超时
            img.onload = function() {
                clearTimeout(secondTimeout);
                // 转换为dataURL并存入缓存
                const canvas = document.createElement('canvas');
                canvas.width = img.width;
                canvas.height = img.height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                const dataUrl = canvas.toDataURL('image/png');
                saveImageToCache(baseImageUrl, dataUrl);
                
                loadingElement.style.display = 'none';
                imageElement.style.display = 'block';
                imageElement.src = dataUrl;
                statusElement.textContent = '加载完成';
                
                // 更新R²值
                if (csvData.length > 0) {
                    const r2Element = document.getElementById(`pred-r2-${processNum}`);
                    const index = Math.min(iter - 1, csvData.length - 1);
                    let r2Value = null;
                    if (index >= 0) {
                        r2Value = csvData[index].r2Score;
                    }
                    if (r2Value === null && csvData.length > 0) {
                        r2Value = csvData[csvData.length - 1].r2Score;
                    }
                    r2Element.textContent = r2Value !== null ? 
                        `R²: ${r2Value.toFixed(3)}` : 'R²: N/A';
                }
                
                resolve();
            };
        }, 20000);
        
        // 图片加载成功
        img.onload = function() {
            clearTimeout(timeout);
            
            // 转换为dataURL并存入缓存
            const canvas = document.createElement('canvas');
            canvas.width = img.width;
            canvas.height = img.height;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            const dataUrl = canvas.toDataURL('image/png');
            saveImageToCache(baseImageUrl, dataUrl);
            
            loadingElement.style.display = 'none';
            imageElement.style.display = 'block';
            imageElement.src = dataUrl;
            statusElement.textContent = '加载完成';
            
            // 更新R²值
            if (csvData.length > 0) {
                const r2Element = document.getElementById(`pred-r2-${processNum}`);
                const index = Math.min(iter - 1, csvData.length - 1);
                let r2Value = null;
                if (index >= 0) {
                    r2Value = csvData[index].r2Score;
                }
                if (r2Value === null && csvData.length > 0) {
                    r2Value = csvData[csvData.length - 1].r2Score;
                }
                r2Element.textContent = r2Value !== null ? 
                    `R²: ${r2Value.toFixed(3)}` : 'R²: N/A';
            }
            
            resolve();
        };
        
        img.onerror = function() {
            clearTimeout(timeout);
            loadingElement.innerHTML = `
                <i class="fas fa-exclamation-triangle text-warning fa-3x"></i>
                <p class="mt-2">图片加载失败</p>
                <p class="mt-2">请检查文件是否存在: ${baseImageUrl}</p>
                <button class="btn btn-sm btn-primary mt-2" onclick="updatePredImage(${processNum}, ${iter})">重试</button>
            `;
            statusElement.style.display = 'none';
            reject(new Error('图片加载失败'));
        };
        
        // 尝试加载图片
        img.src = imageUrl;
    });
}

// 更新其他标签页的图片
function updateOtherTabImages(iter) {
    // 确保迭代在有效范围内
    if (iter < 1 || iter > totalIterations || totalIterations === 0 || !phaseName) return;
    
    // 更新凸包信息图片
    updateTabImage('convex-hull', iter, 'convex_hull');
    
    // 更新特征分析图片
    updateTabImage('features', iter, 'features_importance');
    
    // 更新日志信息图片
    updateTabImage('logs', iter, 'training_logs');
}

// 更新指定标签页的图片
function updateTabImage(tabId, iter, imagePrefix) {
    const loadingElement = document.getElementById(`${tabId}-loading`);
    const imageElement = document.getElementById(`${tabId}-image`);
    const pathElement = document.getElementById(`${tabId}-image-path`);
    const cacheIndicator = document.getElementById(`${tabId}-cache`);
    
    if (!loadingElement || !imageElement || !pathElement) return;
    
    // 显示加载状态
    loadingElement.style.display = 'block';
    imageElement.style.display = 'none';
    cacheIndicator.style.display = 'none';
    
    // 构建图片URL，包含相名称
    const formattedIter = String(iter).padStart(4, '0');
    const baseImageUrl = `${IMAGE_BASE_PATH}${imagePrefix}_${phaseName}_iter${formattedIter}_process2.png`;
    
    // 检查缓存
    const cachedImage = getImageFromCache(baseImageUrl);
    if (cachedImage) {
        // 使用缓存图片
        imageElement.src = cachedImage.data;
        loadingElement.style.display = 'none';
        imageElement.style.display = 'block';
        cacheIndicator.style.display = 'block';
        pathElement.textContent = `图片路径: ${baseImageUrl} (已缓存)`;
        console.log(`使用缓存加载${tabId}图:`, baseImageUrl);
        return;
    }
    
    // 添加时间戳避免缓存
    const timestamp = new Date().getTime();
    const imageUrl = `${baseImageUrl}?timestamp=${timestamp}`;
    
    // 显示图片路径
    pathElement.textContent = `图片路径: ${baseImageUrl}`;
    
    // 清除之前的事件监听
    imageElement.onload = null;
    imageElement.onerror = null;
    
    // 创建图片对象用于预加载
    const img = new Image();
    
    // 设置超时
    const timeout = setTimeout(() => {
        loadingElement.innerHTML = `
            <i class="fas fa-exclamation-triangle text-warning fa-3x"></i>
            <p class="mt-2">图片加载超时</p>
            <p class="mt-2">请检查网络连接或文件路径</p>
            <button class="btn btn-sm btn-primary mt-2" onclick="updateTabImage('${tabId}', ${iter}, '${imagePrefix}')">重试</button>
        `;
    }, 20000);
    
    // 图片加载成功
    img.onload = function() {
        clearTimeout(timeout);
        
        // 转换为dataURL并存入缓存
        const canvas = document.createElement('canvas');
        canvas.width = img.width;
        canvas.height = img.height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0);
        const dataUrl = canvas.toDataURL('image/png');
        saveImageToCache(baseImageUrl, dataUrl);
        
        loadingElement.style.display = 'none';
        imageElement.style.display = 'block';
        imageElement.src = dataUrl;
        cacheIndicator.style.display = 'block';
    };
    
    img.onerror = function() {
        clearTimeout(timeout);
        loadingElement.innerHTML = `
            <i class="fas fa-exclamation-triangle text-warning fa-3x"></i>
            <p class="mt-2">图片加载失败</p>
            <p class="mt-2">请检查文件是否存在: ${baseImageUrl}</p>
            <button class="btn btn-sm btn-primary mt-2" onclick="updateTabImage('${tabId}', ${iter}, '${imagePrefix}')">重试</button>
        `;
    };
    
    img.src = imageUrl;
}

// 切换迭代
function changeIteration(iter) {
    if (iter < 1 || iter > totalIterations || totalIterations === 0) return;
    
    currentIteration = iter;
    updateIterationDisplay();
    
    // 从CSV更新指标
    updateMetricsFromCsv();
    
    // 更新所有相关图片
    updateAllImages();
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    // 初始化数据获取
    initDataFetch();
    
    // 绑定迭代控制按钮事件
    document.getElementById('first-iter').addEventListener('click', () => {
        changeIteration(1);
    });
    
    document.getElementById('prev-iter').addEventListener('click', () => {
        changeIteration(currentIteration - 1);
    });
    
    document.getElementById('next-iter').addEventListener('click', () => {
        changeIteration(currentIteration + 1);
    });
    
    document.getElementById('last-iter').addEventListener('click', () => {
        changeIteration(itermax);
    });
    
    // 预测图片1导航控制（第二张图）
    document.getElementById('first-pred-1').addEventListener('click', () => {
        updatePredImage(1, predImageMinIter);
    });
    
    document.getElementById('prev-pred-1').addEventListener('click', () => {
        updatePredImage(1, currentPredIter1 - 1);
    });
    
    document.getElementById('next-pred-1').addEventListener('click', () => {
        updatePredImage(1, currentPredIter1 + 1);
    });
    
    document.getElementById('last-pred-1').addEventListener('click', () => {
        updatePredImage(1, itermax);
    });
    
    document.getElementById('iter-pred-1').addEventListener('change', function() {
        const iter = parseInt(this.value);
        if (!isNaN(iter)) {
            updatePredImage(1, iter);
        }
    });
    
    // 预测图片2导航控制（第三张图）
    document.getElementById('first-pred-2').addEventListener('click', () => {
        updatePredImage(2, predImageMinIter);
    });
    
    document.getElementById('prev-pred-2').addEventListener('click', () => {
        updatePredImage(2, currentPredIter2 - 1);
    });
    
    document.getElementById('next-pred-2').addEventListener('click', () => {
        updatePredImage(2, currentPredIter2 + 1);
    });
    
    document.getElementById('last-pred-2').addEventListener('click', () => {
        updatePredImage(2, itermax);
    });
    
    document.getElementById('iter-pred-2').addEventListener('change', function() {
        const iter = parseInt(this.value);
        if (!isNaN(iter)) {
            updatePredImage(2, iter);
        }
    });
    
    // 标签页切换时更新图片
    const tabElements = document.querySelectorAll('#vizTabs button[data-bs-toggle="tab"]');
    tabElements.forEach(tab => {
        tab.addEventListener('shown.bs.tab', function() {
            updateAllImages();
        });
    });
});