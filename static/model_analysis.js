
// 全局变量
let currentStep = 1;
const totalSteps = 5;
let sublatticeNumber = 5; // 从input.json获取的值
let selectedModel = null;
let sublAssessRunner = null; // 用于存储subl_assess实例引用
// 缓存图片路径，避免重复请求
let cachedPlotPath = localStorage.getItem('cachedPlotPath') || null;
const CACHE_EXPIRY = 3600000; // 缓存有效期1小时（毫秒）
let cachedPlotTimestamp = localStorage.getItem('cachedPlotTimestamp') ? 
    parseInt(localStorage.getItem('cachedPlotTimestamp')) : 0;

// 交互式图表相关变量
let csvData = null;
let chart = null;
let chartConfig = null;
let csvFilePath = "/static/table/model_score.csv"; // 默认CSV文件路径

// DOM元素
const dropArea = document.getElementById('dropArea');
const csvFileInput = document.getElementById('csvFile');
const fileInfo = document.getElementById('fileInfo');
const columnSelectors = document.getElementById('columnSelectors');
const xAxisSelect = document.getElementById('xAxis');
const yAxisContainer = document.getElementById('yAxisContainer');
const addYAxisButton = document.getElementById('addYAxis'); // 修正变量名，避免与函数冲突
const chartTypeSelect = document.getElementById('chartType');
const plotButton = document.getElementById('plotButton');
const dataPreview = document.getElementById('dataPreview');
const previewTable = document.getElementById('previewTable');
const chartPlaceholder = document.getElementById('chartPlaceholder');
const chartControls = document.getElementById('chartControls');
const zoomInBtn = document.getElementById('zoomIn');
const zoomOutBtn = document.getElementById('zoomOut');
const resetZoomBtn = document.getElementById('resetZoom');
const downloadChartBtn = document.getElementById('downloadChart');
const csvFileNameEl = document.getElementById('csvFileName');
const csvFilePathInput = document.getElementById('csv-file-path');

// 初始化图表上下文
const ctx = document.getElementById('dataChart').getContext('2d');

// 步骤1: 确认计算按钮事件
document.getElementById('step1-calculate').addEventListener('click', async () => {
    const userInput = document.getElementById('user-input');
    const maskInput = document.getElementById('mask-input');
    const InputFilePathInput = document.getElementById('input-file-path');
    
    const user = userInput.value.trim();
    const mask = maskInput.value.trim();
    const input_file_path = InputFilePathInput.value.trim();
    
    // 获取CSV文件路径
    csvFilePath = csvFilePathInput.value.trim() || "/static/table/model_score.csv";
    
    // 输入验证
    if (!user) {
        alert('请输入用户标识（user）');
        userInput.focus();
        return;
    }
    
    if (!mask || isNaN(parseInt(mask))) {
        alert('请输入有效的掩码值（mask必须是整数）');
        maskInput.focus();
        return;
    }
    
    try {
        // 显示计算状态
        const statusEl = document.getElementById('step1-status');
        const statusTextEl = document.getElementById('step1-status-text');
        statusEl.className = 'calculation-status status-pending';
        statusTextEl.innerHTML = '正在生成TDB文件... <i class="fas fa-spinner fa-spin ml-1"></i>';
        
        console.log('准备调用/generate_tdb API', {
            user: user,
            mask: parseInt(mask),
            input_file_path: input_file_path
        });
        
        // 调用API
        const response = await fetch('/generate_tdb', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user: user,
                mask: parseInt(mask),
                input_file_path: input_file_path
            })
        });
        
        console.log('API响应状态码:', response.status);
        const result = await response.json();
        console.log('API响应结果:', result);

        if (response.ok && result.success) {
            // 保存sublatticeNumber
            sublatticeNumber = result.sublatticeNumber;
            // 初始化亚点阵模型复选框
            initSublatticeCheckboxes();
            
            // 更新状态为成功
            statusEl.className = 'calculation-status status-success';
            statusTextEl.innerHTML = `<i class="fas fa-check-circle me-2"></i> TDB文件生成成功: ${result.file_path || '未知路径'}`;
            
            // 启用下一步按钮
            document.getElementById('step1-next').disabled = false;
        } else {
            // 更新状态为错误
            statusEl.className = 'calculation-status status-error';
            statusTextEl.innerHTML = `<i class="fas fa-exclamation-circle me-2"></i> 操作失败: ${result.message || '服务器未返回错误信息'}`;
        }
        
    } catch (error) {
        console.error('调用API时发生错误:', error);
        // 更新状态为错误
        const statusEl = document.getElementById('step1-status');
        const statusTextEl = document.getElementById('step1-status-text');
        statusEl.className = 'calculation-status status-error';
        statusTextEl.innerHTML = `<i class="fas fa-exclamation-circle me-2"></i> 与服务器通信失败: ${error.message}`;
    }
});

// 步骤1: 下一步按钮事件
document.getElementById('step1-next').addEventListener('click', () => {
    navigateToStep(2);
});

// 步骤2: 确认计算按钮事件
document.getElementById('step2-calculate').addEventListener('click', async function() {
    console.log('检测到确认计算按钮点击');
    
    // 获取选中的模型编号
    const selectedCheckboxes = document.querySelectorAll('#sublattice-checkboxes input:checked');
    const choosenModels = Array.from(selectedCheckboxes).map(checkbox => parseInt(checkbox.value));
    
    console.log('选中的模型:', choosenModels);
    
    // // 验证是否选择了至少一个模型
    // if (choosenModels.length === 0) {
    //     showError('请至少选择一个模型进行分析');
    //     return;
    // }
    
    try {
        // 显示计算状态
        const statusEl = document.getElementById('step2-status');
        const statusTextEl = document.getElementById('step2-status-text');
        statusEl.className = 'calculation-status status-pending';
        const processText = choosenModels.length === 0 
            ? '处理空集请求... <i class="fas fa-spinner fa-spin ml-1"></i>'
            : '正在分析模型... <i class="fas fa-spinner fa-spin ml-1"></i>';
        statusTextEl.innerHTML = processText;
        
        // 禁用计算按钮
        this.disabled = true;
        
        // 第一步：分析模型
        console.log('准备调用API:', '/analyze_models');
        let response = await fetch('/analyze_models', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(choosenModels)
        });
        
        console.log('分析模型API响应状态:', response.status);
        
        if (!response.ok) {
            throw new Error(`服务器返回错误: ${response.status} ${response.statusText}`);
        }
        
        let result = await response.json();
        console.log('分析模型API响应结果:', result);
        
        if (!result.success) {
            throw new Error(`分析失败: ${result.message || '未知错误'}`);
        }
        
        // 更新状态为处理中
        statusTextEl.innerHTML = '正在生成可视化图表... <i class="fas fa-spinner fa-spin ml-1"></i>';
        
        // 第二步：调用绘图接口
        console.log('准备调用绘图API:', '/plot_base_analyze_models');
        response = await fetch('/plot_base_analyze_models', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });
        
        console.log('绘图API响应状态:', response.status);
        
        if (!response.ok) {
            throw new Error(`绘图API返回错误: ${response.status} ${response.statusText}`);
        }
        
        result = await response.json();
        console.log('绘图API响应结果:', result);
        
        if (result.success) {
            // 假设后端返回的图片绝对路径在result.plot_file中
            if (result.plot_file) {
                // 缓存图片路径和时间戳
                cachedPlotPath = result.plot_file;
                cachedPlotTimestamp = Date.now();
                localStorage.setItem('cachedPlotPath', cachedPlotPath);
                localStorage.setItem('cachedPlotTimestamp', cachedPlotTimestamp.toString());
                
                // 更新状态为成功
                statusEl.className = 'calculation-status status-success';
                statusTextEl.innerHTML = `<i class="fas fa-check-circle me-2"></i> 模型分析和绘图成功，共分析了 ${choosenModels.length} 个模型`;
                
                // 启用下一步按钮
                document.getElementById('step2-next').disabled = false;
            } else {
                throw new Error('服务器未返回图片路径');
            }
        } else {
            throw new Error(`绘图失败: ${result.message || '未知错误'}`);
        }
        
    } catch (error) {
        console.error('操作过程中发生错误:', error);
        // 更新状态为错误
        const statusEl = document.getElementById('step2-status');
        const statusTextEl = document.getElementById('step2-status-text');
        statusEl.className = 'calculation-status status-error';
        statusTextEl.innerHTML = `<i class="fas fa-exclamation-circle me-2"></i> 操作失败: ${error.message}`;
    } finally {
        // 恢复计算按钮状态
        this.disabled = false;
    }
});

// 步骤2: 下一步按钮事件
document.getElementById('step2-next').addEventListener('click', function() {
    navigateToStep(3);
    // 导航后显示图片和加载CSV数据
    checkAndDisplayCachedPlot();
    loadCSVData();
});

// 步骤3: 确认计算按钮事件
document.getElementById('step3-calculate').addEventListener('click', async function() {
    try {
        // 显示计算状态
        const statusEl = document.getElementById('step3-status');
        const statusTextEl = document.getElementById('step3-status-text');
        statusEl.className = 'calculation-status status-pending';
        statusTextEl.innerHTML = '正在生成可视化结果... <i class="fas fa-spinner fa-spin ml-1"></i>';
        
        // 禁用计算按钮
        this.disabled = true;
        
        // 模拟计算过程
        await new Promise(resolve => setTimeout(resolve, 2000));
        
        // 加载CSV数据
        await loadCSVData();
        
        // 检查是否有缓存的图片
        checkAndDisplayCachedPlot();
        
        // 更新状态为成功
        statusEl.className = 'calculation-status status-success';
        statusTextEl.innerHTML = `<i class="fas fa-check-circle me-2"></i> 可视化结果生成成功`;
        
        // 启用下一步按钮
        document.getElementById('step3-next').disabled = false;
        document.getElementById('step3-to-5').disabled = false;
        
    } catch (error) {
        console.error('可视化计算过程中发生错误:', error);
        // 更新状态为错误
        const statusEl = document.getElementById('step3-status');
        const statusTextEl = document.getElementById('step3-status-text');
        statusEl.className = 'calculation-status status-error';
        statusTextEl.innerHTML = `<i class="fas fa-exclamation-circle me-2"></i> 可视化失败: ${error.message}`;
    } finally {
        // 恢复计算按钮状态
        this.disabled = false;
    }
});

// 步骤3: 下一步按钮事件
document.getElementById('step3-next').addEventListener('click', function() {
    navigateToStep(4);
});

// 步骤3: 直接输出模型按钮事件
document.getElementById('step3-to-5').addEventListener('click', function() {
    navigateToStep(5);
});

// DOM元素加载完成后执行
document.addEventListener('DOMContentLoaded', function() {

    initModelConfirmEvent();
    Step5initModelConfirmEvent();

    // 初始化亚点阵模型复选框
    initSublatticeCheckboxes();
    
    // 初始化事件监听器
    initEventListeners();
    
    // 初始化交互式图表事件
    initChartEventListeners();
    
    // 如果当前在步骤3，且有缓存的图片路径，则显示图片
    if (window.location.hash === '#step3' || currentStep === 3) {
        checkAndDisplayCachedPlot();
        // 尝试加载CSV数据
        loadCSVData();
    }
});

document.getElementById('updateChart').addEventListener('click', function() {
    // 获取所有选中的选项
    const yAxisSelect = document.getElementById('yAxisSelect');
    const selectedYValues = Array.from(yAxisSelect.selectedOptions).map(option => option.value);
    
    // 后续处理逻辑需要根据选中的多个值进行调整
    updateChart(selectedYValues);
});

// 初始化图表事件监听器
function initChartEventListeners() {
    // 添加Y列按钮事件
    addYAxisButton.addEventListener('click', addYAxisConfig);
    
    // 生成图表按钮事件
    plotButton.addEventListener('click', generateChart);
    
    // 图表控制事件
    zoomInBtn.addEventListener('click', () => {
        if (chart) {
            chart.zoom(1.3); // 放大1.3倍
        }
    });
    
    zoomOutBtn.addEventListener('click', () => {
        if (chart) {
            chart.zoom(0.7); // 缩小到0.7倍
        }
    });
    
    resetZoomBtn.addEventListener('click', () => {
        if (chart) {
            chart.resetZoom();
        }
    });
    
    downloadChartBtn.addEventListener('click', () => {
        if (chart) {
            // 获取图表的图片URL
            const imageURL = document.getElementById('dataChart').toDataURL('image/png');
            
            // 创建下载链接
            const downloadLink = document.createElement('a');
            downloadLink.href = imageURL;
            downloadLink.download = 'model-analysis-chart.png';
            downloadLink.click();
        }
    });
}

// 加载CSV数据
function loadCSVData() {
    if (!csvFilePath) return;
    
    // 显示文件名
    csvFileNameEl.textContent = csvFilePath.split('/').pop();
    
    // 尝试从服务器加载CSV文件
    return new Promise((resolve, reject) => {
        fetch(csvFilePath)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`无法加载CSV文件: ${response.statusText}`);
                }
                return response.text();
            })
            .then(csvText => {
                // 解析CSV文本
                Papa.parse(csvText, {
                    header: true,
                    dynamicTyping: true,
                    complete: function(results) {
                        csvData = results;
                        populateColumnSelectors(results.meta.fields);
                        showDataPreview(results.data);
                        resolve();
                    },
                    error: function(error) {
                        showError(`解析CSV时出错: ${error.message}`);
                        console.error(error);
                        reject(error);
                    }
                });
            })
            .catch(error => {
                showError(`加载CSV文件失败: ${error.message}`);
                console.error('加载CSV文件时出错:', error);
                
                // 提供示例数据用于演示
                provideSampleData();
                resolve();
            });
    });
}

// 提供示例数据用于演示
function provideSampleData() {
    const sampleCSV = `model,RMSE,准确率,F1分数,训练时间
模型1,0.87,0.89,0.87,12.5
模型2,1.23,0.92,0.90,18.3
模型3,1.56,0.87,0.85,15.2
模型4,1.89,0.91,0.89,16.7
模型5,2.10,0.88,0.86,14.9`;
    
    Papa.parse(sampleCSV, {
        header: true,
        dynamicTyping: true,
        complete: function(results) {
            csvData = results;
            populateColumnSelectors(results.meta.fields);
            showDataPreview(results.data);
            showAlert('使用示例数据进行可视化演示');
        }
    });
}

// 添加Y列配置
function addYAxisConfig() {
    const yAxisGroups = document.querySelectorAll('.y-axis-group');
    const newIndex = yAxisGroups.length;
    
    const yAxisGroup = document.createElement('div');
    yAxisGroup.className = 'y-axis-group border rounded-md p-3 mb-3';
    
    yAxisGroup.innerHTML = `
        <div class="flex justify-between items-center mb-2">
            <span class="text-sm font-medium">Y轴 ${newIndex + 1}</span>
            <button class="btn btn-sm btn-danger remove-y-axis">
                <i class="fa fa-times"></i>
            </button>
        </div>
        <select class="yAxis form-select form-select-sm mb-2" multiple size="3">
            <!-- 选项将动态生成 -->
        </select>
        <div class="flex items-center gap-2">
            <select class="chart-type-selector form-select form-select-sm" data-axis="${newIndex}">
                <option value="line">折线图</option>
                <option value="bar">柱状图</option>
                <option value="scatter">散点图</option>
            </select>
            <div class="form-check form-switch">
                <input class="form-check-input" type="checkbox" id="yAxisIndependent-${newIndex}" checked>
                <label class="form-check-label text-sm" for="yAxisIndependent-${newIndex}">独立轴</label>
            </div>
        </div>
    `;
    
    yAxisContainer.appendChild(yAxisGroup);
    
    // 复制选项
    if (xAxisSelect.options.length > 0) {
        const newYSelect = yAxisGroup.querySelector('.yAxis');
        Array.from(xAxisSelect.options).forEach(option => {
            const newOption = document.createElement('option');
            newOption.value = option.value;
            newOption.textContent = option.textContent;
            newYSelect.appendChild(newOption);
        });
    }
    
    // 添加删除事件
    yAxisGroup.querySelector('.remove-y-axis').addEventListener('click', function() {
        yAxisGroup.remove();
        updateYAxisUI();
    });
    
    updateYAxisUI();
}


// 更新Y轴UI状态
function updateYAxisUI() {
    const yAxisGroups = document.querySelectorAll('.y-axis-group');
    const removeButtons = document.querySelectorAll('.remove-y-axis');
    
    // 更新序号
    yAxisGroups.forEach((group, index) => {
        group.querySelector('.text-sm.font-medium').textContent = `Y轴 ${index + 1}`;
    });
    
    // 控制删除按钮状态
    if (yAxisGroups.length <= 1) {
        removeButtons[0].disabled = true;
    } else {
        removeButtons.forEach(btn => btn.disabled = false);
    }
}

// 更新删除按钮状态
function updateRemoveButtons() {
    const removeButtons = document.querySelectorAll('.remove-y-column');
    if (removeButtons.length <= 1) {
        removeButtons.forEach(btn => btn.disabled = true);
    } else {
        removeButtons.forEach(btn => btn.disabled = false);
    }
}

// 填充列选择器
function populateColumnSelectors(fields) {
    // 清空现有选项
    xAxisSelect.innerHTML = '';
    
    // 添加选项
    fields.forEach(field => {
        const xOption = document.createElement('option');
        xOption.value = field;
        xOption.textContent = field;
        xAxisSelect.appendChild(xOption);
    });
    
    // 更新所有Y轴选择器
    document.querySelectorAll('.yAxis').forEach((select, index) => {
        // 保存当前选中的值
        const currentValue = select.value;
        
        // 清空并重新填充选项
        select.innerHTML = '';
        fields.forEach(field => {
            const yOption = document.createElement('option');
            yOption.value = field;
            yOption.textContent = field;
            select.appendChild(yOption);
        });
        
        // 尝试恢复之前的选择
        if (currentValue && fields.includes(currentValue)) {
            select.value = currentValue;
        } else if (index < fields.length && fields[index] !== xAxisSelect.value) {
            // 否则选择第一个不同于X轴的选项
            select.value = fields.find(f => f !== xAxisSelect.value) || fields[0];
        }
    });
    
    // 默认选择第一列作为X轴
    if (fields.length >= 1) {
        xAxisSelect.selectedIndex = 0;
    }
    
    // 确保至少有一个Y轴选择器
    if (document.querySelectorAll('.yAxis').length === 0) {
        addYColumn();
    }
}

// 显示数据预览
function showDataPreview(data) {
    previewTable.innerHTML = '';
    
    // 最多显示5行预览
    const previewData = data.slice(0, 5);
    const fields = Object.keys(previewData[0] || {});
    
    // 创建表头
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    fields.forEach(field => {
        const th = document.createElement('th');
        th.textContent = field;
        th.className = 'px-2 py-1 border-b text-left';
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    previewTable.appendChild(thead);
    
    // 创建表体
    const tbody = document.createElement('tbody');
    previewData.forEach(row => {
        const tr = document.createElement('tr');
        fields.forEach(field => {
            const td = document.createElement('td');
            td.textContent = row[field] !== undefined ? row[field] : '';
            td.className = 'px-2 py-1 border-b';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    previewTable.appendChild(tbody);
    
    // 如果数据超过5行，显示提示
    if (data.length > 5) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = fields.length;
        td.textContent = `... 还有 ${data.length - 5} 行数据未显示`;
        td.className = 'px-2 py-1 text-center text-gray-500';
        tr.appendChild(td);
        tbody.appendChild(tr);
    }
}

// 生成图表
function generateChart() {
    if (!csvData) {
        showError('没有可用的CSV数据，请检查文件路径');
        return;
    }
    
    const xAxis = xAxisSelect.value;
    const yAxisGroups = document.querySelectorAll('.y-axis-group');
    
    if (!xAxis || yAxisGroups.length === 0) {
        alert('请选择X轴和至少一个Y轴配置');
        return;
    }
    
    // 隐藏占位符
    chartPlaceholder.classList.add('hidden');
    
    // 准备数据集和Y轴配置
    const datasets = [];
    const yAxes = [];
    const colors = ['#3B82F6', '#10B981', '#EF4444', '#F59E0B', '#8B5CF6', '#EC4899', '#06B6D4'];
    
    yAxisGroups.forEach((group, axisIndex) => {
        const ySelect = group.querySelector('.yAxis');
        const chartType = group.querySelector('.chart-type-selector').value;
        const isIndependent = group.querySelector('.form-check-input').checked;
        
        // 获取当前Y轴选中的所有数据列
        const selectedColumns = Array.from(ySelect.selectedOptions).map(option => option.value);
        
        if (selectedColumns.length === 0) return;
        
        // 为独立Y轴创建配置
        if (isIndependent) {
            yAxes.push({
                id: `y-axis-${axisIndex}`,
                position: axisIndex % 2 === 0 ? 'left' : 'right',
                grid: {
                    drawOnChartArea: false, // 不在主图表区域绘制网格
                },
                title: {
                    display: true,
                    text: `Y轴 ${axisIndex + 1}`
                }
            });
        } else if (yAxes.length === 0) {
            // 默认Y轴
            yAxes.push({
                id: 'y-axis-0',
                position: 'left',
                title: {
                    display: true,
                    text: '值'
                }
            });
        }
        
        // 为每个选中的列创建数据集
        selectedColumns.forEach((column, colIndex) => {
            const colorIndex = (axisIndex * 10 + colIndex) % colors.length;
            const color = colors[colorIndex];
            
            datasets.push({
                label: column,
                data: csvData.data.map(row => ({
                    x: row[xAxis],
                    y: row[column]
                })),
                borderColor: color,
                backgroundColor: `${color}33`,
                borderWidth: 2,
                pointRadius: 3,
                pointHoverRadius: 6,
                tension: 0.1,
                fill: false,
                type: chartType,
                yAxisID: isIndependent ? `y-axis-${axisIndex}` : 'y-axis-0'
            });
        });
    });
    
    // 图表配置
    chartConfig = {
        data: {
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    position: 'top',
                },
                tooltip: {
                    callbacks: {
                        title: function(tooltipItems) {
                            return `${xAxis}: ${tooltipItems[0].raw.x}`;
                        }
                    }
                },
                title: {
                    display: true,
                    text: `多Y轴数据可视化: ${xAxis} 对比分析`
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: xAxis
                    },
                    grid: {
                        display: true,
                        color: 'rgba(0, 0, 0, 0.05)'
                    }
                },
                y: yAxes.length > 0 ? undefined : {
                    title: {
                        display: true,
                        text: '值'
                    }
                }
            }
        }
    };
    
    // 添加多Y轴配置
    yAxes.forEach(axis => {
        chartConfig.options.scales[axis.id] = axis;
    });
    
    // 销毁现有图表（如果存在）
    if (chart) {
        chart.destroy();
    }
    
    // 创建新图表
    chart = new Chart(ctx, chartConfig);
}

// 检查并显示缓存的图片
function checkAndDisplayCachedPlot() {
    const now = Date.now();
    // 检查缓存是否存在且未过期
    if (cachedPlotPath && (now - cachedPlotTimestamp) < CACHE_EXPIRY) {
        displayPlotImage(cachedPlotPath);
    } else if (cachedPlotPath) {
        // 缓存过期，清除缓存
        clearPlotCache();
    }
}

// 显示图片
function displayPlotImage(imagePath) {
    const loading = document.getElementById('plot-loading');
    const error = document.getElementById('plot-error');
    const image = document.getElementById('model-plot-image');
    
    // 重置状态
    loading.style.display = 'flex';
    error.style.display = 'none';
    image.style.display = 'none';
    
    // 创建图片对象来预加载，检测是否能成功加载
    const img = new Image();
    img.src = imagePath;
    
    img.onload = function() {
        // 图片加载成功
        loading.style.display = 'none';
        image.src = imagePath;
        image.style.display = 'block';
    };
    
    img.onerror = function() {
        // 图片加载失败
        loading.style.display = 'none';
        error.style.display = 'block';
        error.textContent = `无法加载图片: ${imagePath}\n请尝试重新生成或检查路径是否正确。`;
    };
}

// 清除图片缓存
function clearPlotCache() {
    cachedPlotPath = null;
    cachedPlotTimestamp = 0;
    localStorage.removeItem('cachedPlotPath');
    localStorage.removeItem('cachedPlotTimestamp');
}

// 初始化亚点阵模型复选框
function initSublatticeCheckboxes() {
    const container = document.getElementById('sublattice-checkboxes');
    container.innerHTML = '';
    
    // 显示sublattice_number值和最大模型编号
    document.getElementById('sublattice-number-display').textContent = sublatticeNumber;
    const maxModelNumber = sublatticeNumber - 1;
    document.getElementById('max-model-number').textContent = maxModelNumber;
    
    // 根据sublatticeNumber生成2到n-1的复选框
    for (let i = 2; i < sublatticeNumber; i++) {
        const checkboxItem = document.createElement('div');
        checkboxItem.className = 'checkbox-item';
        
        checkboxItem.innerHTML = `
            <input type="checkbox" id="sublattice-${i}" value="${i}">
            <label for="sublattice-${i}">模型 ${i}</label>
        `;
        
        container.appendChild(checkboxItem);
    }
}

/**
 * 从CSV数据中解析模型信息，动态生成模型卡片
 * 处理model列格式：4_A_B_B_C_D.csv → site=4,model=A:B:B:C:D
 */
function renderModelCardsFromCSV() {
    const modelContainer = document.getElementById('csv-model-selection');
    const confirmBtn = document.getElementById('confirm-model');
    modelContainer.innerHTML = '';

    // 1. 先创建表格结构（仅一次）
    modelContainer.innerHTML = `
        <div class="table-responsive">
            <table class="model-table table table-hover table-sm">
            <thead class="table-light">
                <tr>
                <th>选择</th>
                <th>Site</th>
                <th>模型公式</th>
                <th>RMSE值</th>
                </tr>
            </thead>
            <tbody id="model-table-body"></tbody>
            </table>
        </div>
    `;
    const tableBody = document.getElementById('model-table-body');

    // 2. 检查CSV数据
    if (!csvData || !csvData.data || csvData.data.length === 0) {
        tableBody.innerHTML = `
            <tr><td colspan="4" class="text-center text-muted py-3">
                <i class="fas fa-exclamation-circle me-1"></i> 无有效模型数据
            </td></tr>
        `;
        confirmBtn.disabled = true;
        return;
    }

    // 3. 提取列信息
    const hasModelCol = csvData.meta.fields.includes('model');
    const hasRMSECol = csvData.meta.fields.includes('RMSE');
    if (!hasModelCol) {
        tableBody.innerHTML = `
            <tr><td colspan="4" class="text-center text-danger py-3">
                <i class="fas fa-exclamation-circle me-1"></i> CSV中缺少"model"列
            </td></tr>
        `;
        confirmBtn.disabled = true;
        return;
    }

    // 4. 循环处理数据（仅添加行，不重建表格）
    const uniqueModels = new Map();
    csvData.data.forEach(row => {
        const modelFileName = row.model || '';
        if (!modelFileName.endsWith('.csv') || uniqueModels.has(modelFileName)) return;
        uniqueModels.set(modelFileName, row);

        // 解析模型信息
        const modelName = modelFileName.split('.')[0];
        const modelParts = modelName.split('_');
        if (modelParts.length < 2) return;

        const site = modelParts[0];
        const modelFormula = modelParts.slice(1).join(':');
        const rmse = hasRMSECol ? (row.RMSE || '未知') : '未知';
        
        // 创建行并添加到表格（累加操作）
        const tableRow = document.createElement('tr');
        tableRow.className = 'model-row';
        tableRow.innerHTML = `
            <td><input type="radio" name="model-select" class="model-radio"></td>
            <td>${site}</td>
            <td class="model-formula">${modelFormula}</td>
            <td>${rmse}</td>
        `;

        // 绑定选择事件
        tableRow.addEventListener('click', () => {
            tableRow.querySelector('.model-radio').checked = true;
            document.querySelectorAll('.model-row').forEach(r => r.classList.remove('selected'));
            tableRow.classList.add('selected');
            selectedModel = modelFileName;
            confirmBtn.disabled = false;
            document.getElementById('step4-next').disabled = false;
        });

        tableBody.appendChild(tableRow); // 关键：累加行，而非覆盖
    });

    // 处理无有效模型的情况
    if (uniqueModels.size === 0) {
        tableBody.innerHTML = `
            <tr><td colspan="4" class="text-center text-danger py-3">
                <i class="fas fa-exclamation-circle me-1"></i> CSV中无有效模型数据
            </td></tr>
        `;
        confirmBtn.disabled = true;
    }
}

// step5-generate
function Step5renderModelCardsFromCSV() {
    const modelContainer = document.getElementById('step5-csv-model-selection');
    const confirmBtn = document.getElementById('step5-confirm-model');
    modelContainer.innerHTML = '';

    // 1. 先创建表格结构（仅一次）
    modelContainer.innerHTML = `
        <div class="table-responsive">
            <table class="model-table table table-hover table-sm">
            <thead class="table-light">
                <tr>
                <th>选择</th>
                <th>Site</th>
                <th>模型公式</th>
                <th>RMSE值</th>
                </tr>
            </thead>
            <tbody id="step5-model-table-body"></tbody>
            </table>
        </div>
    `;
    const tableBody = document.getElementById('step5-model-table-body');

    // 2. 检查CSV数据
    if (!csvData || !csvData.data || csvData.data.length === 0) {
        tableBody.innerHTML = `
            <tr><td colspan="4" class="text-center text-muted py-3">
                <i class="fas fa-exclamation-circle me-1"></i> 无有效模型数据
            </td></tr>
        `;
        confirmBtn.disabled = true;
        return;
    }

    // 3. 提取列信息
    const hasModelCol = csvData.meta.fields.includes('model');
    const hasRMSECol = csvData.meta.fields.includes('RMSE');
    if (!hasModelCol) {
        tableBody.innerHTML = `
            <tr><td colspan="4" class="text-center text-danger py-3">
                <i class="fas fa-exclamation-circle me-1"></i> CSV中缺少"model"列
            </td></tr>
        `;
        confirmBtn.disabled = true;
        return;
    }

    // 4. 循环处理数据（仅添加行，不重建表格）
    const uniqueModels = new Map();
    csvData.data.forEach(row => {
        const modelFileName = row.model || '';
        if (!modelFileName.endsWith('.csv') || uniqueModels.has(modelFileName)) return;
        uniqueModels.set(modelFileName, row);

        // 解析模型信息
        const modelName = modelFileName.split('.')[0];
        const modelParts = modelName.split('_');
        if (modelParts.length < 2) return;

        const site = modelParts[0];
        const modelFormula = modelParts.slice(1).join(':');
        const rmse = hasRMSECol ? (row.RMSE || '未知') : '未知';
        
        // 创建行并添加到表格（累加操作）
        const tableRow = document.createElement('tr');
        tableRow.className = 'model-row';
        tableRow.innerHTML = `
            <td><input type="radio" name="model-select" class="model-radio"></td>
            <td>${site}</td>
            <td class="model-formula">${modelFormula}</td>
            <td>${rmse}</td>
        `;

        // 绑定选择事件
        tableRow.addEventListener('click', () => {
            tableRow.querySelector('.model-radio').checked = true;
            document.querySelectorAll('.model-row').forEach(r => r.classList.remove('selected'));
            tableRow.classList.add('selected');
            selectedModel = modelFileName;
            confirmBtn.disabled = false;
            document.getElementById('export-model').disabled = false;
        });

        tableBody.appendChild(tableRow); // 关键：累加行，而非覆盖
    });

    // 处理无有效模型的情况
    if (uniqueModels.size === 0) {
        tableBody.innerHTML = `
            <tr><td colspan="4" class="text-center text-danger py-3">
                <i class="fas fa-exclamation-circle me-1"></i> CSV中无有效模型数据
            </td></tr>
        `;
        confirmBtn.disabled = true;
    }
}

// 初始化模型确认按钮事件
function initModelConfirmEvent() {
    const confirmBtn = document.getElementById('confirm-model');
    const tipEl = document.getElementById('model-confirm-tip');
    const loadingEl = document.getElementById('element-loading');
    const dynamicGroupsEl = document.getElementById('dynamic-element-groups');
    const threeBoxEl = document.getElementById('three-box-selection');

    confirmBtn.addEventListener('click', async () => {
        if (!selectedModel) {
            showError('请先选择一个模型');
            return;
        }

        try {
            // 1. 切换状态：隐藏提示→显示加载
            tipEl.style.display = 'none';
            confirmBtn.disabled = true; // 禁用确认按钮，避免重复请求
            loadingEl.style.display = 'block';
            dynamicGroupsEl.style.display = 'none';
            threeBoxEl.style.display = 'none';

            // 2. 向后端请求二维元素列表（传递选中的模型）
            const response = await fetch('/get_element_groups', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ selected_model: selectedModel })
            });

            if (!response.ok) {
                throw new Error(`请求失败：${response.status} ${response.statusText}`);
            }

            const result = await response.json();
            if (!result.success || !Array.isArray(result.element_groups)) {
                throw new Error('后端未返回有效二维元素列表');
            }

            const elementGroups = result.element_groups;
            if (elementGroups.length === 0) {
                throw new Error('后端返回的元素列表为空');
            }

            // 3. 渲染元素小框（数量=二维列表长度）
            renderDynamicElementGroups(elementGroups);

            // 4. 切换状态：隐藏加载→显示小框和三框
            loadingEl.style.display = 'none';
            dynamicGroupsEl.style.display = 'flex';
            threeBoxEl.style.display = 'block';

            // 5. 初始化三框移动事件（确保元素可移动）
            initGroupMoveEvents();
        } catch (error) {
            // 异常处理：显示错误→恢复提示状态
            console.error('元素组加载错误:', error);
            loadingEl.style.display = 'none';
            tipEl.innerHTML = `<div class="text-center text-danger py-3"><i class="fas fa-exclamation-circle me-1"></i> 加载失败：${error.message}</div>`;
            tipEl.style.display = 'block';
            confirmBtn.disabled = false; // 重新启用确认按钮，允许重试
        }
    });
}


// generate Step5
function Step5initModelConfirmEvent() {
    const confirmBtn = document.getElementById('step5-confirm-model');
    const tipEl = document.getElementById('step5-model-confirm-tip');
    const loadingEl = document.getElementById('step5-element-loading');
    const dynamicGroupsEl = document.getElementById('step5-dynamic-element-groups');
    const twoBoxEl = document.getElementById('step5-two-box-selection');

    confirmBtn.addEventListener('click', async () => {
        if (!selectedModel) {
            showError('请先选择一个模型');
            return;
        }

        try {
            // 1. 切换状态：隐藏提示→显示加载
            tipEl.style.display = 'none';
            confirmBtn.disabled = true; // 禁用确认按钮，避免重复请求
            loadingEl.style.display = 'block';
            dynamicGroupsEl.style.display = 'none';
            twoBoxEl.style.display = 'none';

            // 2. 向后端请求二维元素列表（传递选中的模型）
            const response = await fetch('/get_element_groups', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ selected_model: selectedModel })
            });

            if (!response.ok) {
                throw new Error(`请求失败：${response.status} ${response.statusText}`);
            }

            const result = await response.json();
            if (!result.success || !Array.isArray(result.element_groups)) {
                throw new Error('后端未返回有效二维元素列表');
            }

            const elementGroups = result.element_groups;
            if (elementGroups.length === 0) {
                throw new Error('后端返回的元素列表为空');
            }

            // 3. 渲染元素小框（数量=二维列表长度）
            Step5renderDynamicElementGroups(elementGroups);

            // 4. 切换状态：隐藏加载→显示小框和三框
            loadingEl.style.display = 'none';
            dynamicGroupsEl.style.display = 'flex';
            twoBoxEl.style.display = 'block';

            // 5. 初始化三框移动事件（确保元素可移动）
            Step5initGroupMoveEvents();
        } catch (error) {
            // 异常处理：显示错误→恢复提示状态
            console.error('元素组加载错误:', error);
            loadingEl.style.display = 'none';
            tipEl.innerHTML = `<div class="text-center text-danger py-3"><i class="fas fa-exclamation-circle me-1"></i> 加载失败：${error.message}</div>`;
            tipEl.style.display = 'block';
            confirmBtn.disabled = false; // 重新启用确认按钮，允许重试
        }
    });
}

// 渲染动态元素小框（参数：后端返回的二维列表）
// 渲染动态元素组（带独立三框）
function renderDynamicElementGroups(elementGroups) {
    const container = document.getElementById('dynamic-element-groups');
    container.innerHTML = '';

    elementGroups.forEach((elementList, groupIndex) => {
        if (!Array.isArray(elementList) || elementList.length === 0) return;

        // 创建组容器
        const groupWrapper = document.createElement('div');
        groupWrapper.className = 'element-group-wrapper';
        groupWrapper.dataset.groupIndex = groupIndex;

        // 组标题
        const groupTitle = document.createElement('div');
        groupTitle.className = 'element-group-title';
        groupTitle.textContent = `组${groupIndex + 1}（原始元素：${elementList.join(', ')}）`;
        groupWrapper.appendChild(groupTitle);

        // 创建组内三框容器
        const threeBoxes = document.createElement('div');
        threeBoxes.className = 'group-three-boxes';

        // 三框配置（确定删除、可以删除、必须保留）
        const boxConfigs = [
            { 
                id: `to-delete-${groupIndex}`, 
                title: '确定要删除', 
                badgeClass: 'bg-danger',
                icon: 'trash'
            },
            { 
                id: `can-delete-${groupIndex}`, 
                title: '可以被删除', 
                badgeClass: 'bg-warning',
                icon: 'question-circle'
            },
            { 
                id: `must-keep-${groupIndex}`, 
                title: '必须保留', 
                badgeClass: 'bg-success',
                icon: 'check-circle'
            }
        ];

        // 生成三框
        boxConfigs.forEach(config => {
            const box = document.createElement('div');
            box.className = 'group-box';
            box.id = config.id; // 新增：设置框的id属性
            box.innerHTML = `
                <div class="group-box-title">
                    <i class="fas fa-${config.icon} me-1"></i> ${config.title}
                    <span class="element-count badge ${config.badgeClass} text-white">0</span>
                </div>
                <div class="elements-container min-h-[100px] border-dashed border p-2 rounded"></div>
                <div class="d-flex justify-center gap-2 mt-2">
                    ${config.id.includes('to-delete') ? `
                        <button class="move-btn btn btn-sm btn-outline-secondary" 
                            data-from="${config.id}" 
                            data-to="can-delete-${groupIndex}">
                            <i class="fas fa-chevron-right"></i>
                        </button>
                    ` : ''}
                    ${config.id.includes('can-delete') ? `
                        <button class="move-btn btn btn-sm btn-outline-secondary" 
                            data-from="${config.id}" 
                            data-to="to-delete-${groupIndex}">
                            <i class="fas fa-chevron-left"></i>
                        </button>
                        <button class="move-btn btn btn-sm btn-outline-secondary" 
                            data-from="${config.id}" 
                            data-to="must-keep-${groupIndex}">
                            <i class="fas fa-chevron-right"></i>
                        </button>
                    ` : ''}
                    ${config.id.includes('must-keep') ? `
                        <button class="move-btn btn btn-sm btn-outline-secondary" 
                            data-from="${config.id}" 
                            data-to="can-delete-${groupIndex}">
                            <i class="fas fa-chevron-left"></i>
                        </button>
                    ` : ''}
                </div>
            `;
            threeBoxes.appendChild(box);
        });

        groupWrapper.appendChild(threeBoxes);
        container.appendChild(groupWrapper);

        // 初始化当前组元素到"可以被删除"框
        const canDeleteContainer = document.querySelector(`#can-delete-${groupIndex} .elements-container`);
        elementList.forEach(element => {
            const elementTag = createElementTag(element);
            canDeleteContainer.appendChild(elementTag);
        });

        // 更新当前组计数
        updateGroupBoxCounts(groupIndex);
    });

    // 初始化移动事件
    initGroupMoveEvents();
}

function Step5renderDynamicElementGroups(elementGroups) {
    const container = document.getElementById('step5-dynamic-element-groups');
    // 确保容器存在
    if (!container) {
        console.error('未找到元素容器: step5-dynamic-element-groups');
        return;
    }
    container.innerHTML = '';

    elementGroups.forEach((elementList, groupIndex) => {
        if (!Array.isArray(elementList) || elementList.length === 0) return;

        // 创建组容器
        const groupWrapper = document.createElement('div');
        groupWrapper.className = 'element-group-wrapper';
        groupWrapper.dataset.groupIndex = groupIndex;

        // 组标题
        const groupTitle = document.createElement('div');
        groupTitle.className = 'element-group-title';
        groupTitle.textContent = `组${groupIndex + 1}（原始元素：${elementList.join(', ')}）`;
        groupWrapper.appendChild(groupTitle);

        // 创建组内两框容器
        const twoBoxes = document.createElement('div');
        twoBoxes.className = 'group-two-boxes';
        // 仅保留两个框的配置
        const boxConfigs = [
            { 
                id: `to-delete-${groupIndex}`, 
                title: '可以排出的元素', 
                badgeClass: 'bg-danger',
                icon: 'trash'
            },
            { 
                id: `must-keep-${groupIndex}`, 
                title: '相模型中选择的元素', 
                badgeClass: 'bg-success',
                icon: 'check-circle'
            }
        ];

        // 生成两个框
        boxConfigs.forEach(config => {
            const box = document.createElement('div');
            box.className = 'group-box';
            box.id = config.id;
            box.innerHTML = `
                <div class="group-box-title">
                    <i class="fas fa-${config.icon} me-1"></i> ${config.title}
                    <span class="element-count badge ${config.badgeClass} text-white">0</span>
                </div>
                <div class="elements-container min-h-[100px] border-dashed border p-2 rounded"></div>
                <div class="d-flex justify-center gap-2 mt-2">
                    <!-- 两个框之间的移动按钮 -->
                    ${config.id.includes('to-delete') ? `
                        <button class="move-btn btn btn-sm btn-outline-secondary" 
                            data-from="${config.id}" 
                            data-to="must-keep-${groupIndex}">
                            <i class="fas fa-chevron-right"></i>
                        </button>
                    ` : `
                        <button class="move-btn btn btn-sm btn-outline-secondary" 
                            data-from="${config.id}" 
                            data-to="to-delete-${groupIndex}">
                            <i class="fas fa-chevron-left"></i>
                        </button>
                    `}
                </div>
            `;
            twoBoxes.appendChild(box);
        });

        groupWrapper.appendChild(twoBoxes);
        container.appendChild(groupWrapper);

        // 初始化元素到"相模型中选择的元素"框
        const keepContainer = document.querySelector(`#must-keep-${groupIndex} .elements-container`);
        if (keepContainer) { // 确保容器存在再添加元素
            elementList.forEach(element => {
                const elementTag = createElementTag(element);
                keepContainer.appendChild(elementTag);
            });
        }

        // 更新当前组计数
        Step5updateGroupBoxCounts(groupIndex);
    });
}

// 修复计数更新函数（只处理两个框）
function Step5updateGroupBoxCounts(groupIndex) {
    // 只处理存在的两个框
    const boxIds = [
        `to-delete-${groupIndex}`,
        `must-keep-${groupIndex}`
    ];

    boxIds.forEach(boxId => {
        const box = document.getElementById(boxId);
        if (!box) { // 关键修复：检查元素是否存在
            console.warn(`未找到框元素: ${boxId}`);
            return;
        }
        
        // 查找元素容器和计数徽章
        const elementsContainer = box.querySelector('.elements-container');
        const countBadge = box.querySelector('.element-count');
        
        if (elementsContainer && countBadge) {
            // 安全获取子元素数量
            const count = elementsContainer.children ? elementsContainer.children.length : 0;
            countBadge.textContent = count;
        }
    });
}


/**
 * 初始化元素管理区域，创建三个分类框
 * 并从后端加载元素数据
 */
async function initElementManagement() {
    const elementContainer = document.getElementById('element-groups-container');
    // 清空容器
    elementContainer.innerHTML = '';
    
    try {
        // 创建三个分类框容器
        const container = document.createElement('div');
        container.className = 'element-management-container';
        container.style.display = 'flex';
        container.style.gap = '1rem';
        container.style.flexWrap = 'wrap';
        
        // 创建三个框：确定要删除、可以被删除、必须保留
        const groupConfigs = [
            { 
                id: 'to-delete', 
                title: '确定要删除的元素', 
                class: 'danger',
                icon: 'trash'
            },
            { 
                id: 'can-delete', 
                title: '可以被删除的元素', 
                class: 'warning',
                icon: 'question-circle'
            },
            { 
                id: 'must-keep', 
                title: '必须保留的元素', 
                class: 'success',
                icon: 'check-circle'
            }
        ];
        
        // 创建三个框元素
        groupConfigs.forEach(config => {
            const groupBox = createElementGroupBox(config);
            container.appendChild(groupBox);
        });
        
        elementContainer.appendChild(container);
        
        // 加载元素数据并初始化到"可以被删除"的框中
        await loadAndInitializeElements();
        
        // 添加移动按钮事件监听
        addElementMoveEventListeners();
        
    } catch (error) {
        elementContainer.innerHTML = `
            <div class="text-center text-danger py-3">
                <i class="fas fa-exclamation-circle me-1"></i> 元素管理初始化失败：${error.message}
            </div>
        `;
        console.error('元素管理初始化错误:', error);
    }
}

/**
 * 从后端加载元素数据并初始化到"可以被删除"的框中
 */
async function loadAndInitializeElements() {
    try {
        // 向后端发送请求获取元素数据
        const response = await fetch('/get_element_groups', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ selected_model: selectedModel || '' })
        });

        if (!response.ok) {
            throw new Error(`请求失败：${response.status} ${response.statusText}`);
        }

        const result = await response.json();
        if (!result.success || !Array.isArray(result.element_groups)) {
            throw new Error('后端未返回有效元素组数据');
        }

        // 扁平化元素数组（将二维数组转为一维数组）
        const allElements = [];
        result.element_groups.forEach(group => {
            if (Array.isArray(group)) {
                group.forEach(element => {
                    // 去重添加
                    if (!allElements.includes(element)) {
                        allElements.push(element);
                    }
                });
            }
        });

        // 将所有元素初始添加到"可以被删除"的框中
        const targetContainer = document.querySelector('#can-delete .elements-container');
        allElements.forEach(element => {
            const elementTag = createElementTag(element);
            targetContainer.appendChild(elementTag);
        });
        
        // 更新计数
        updateElementCounts();
        
    } catch (error) {
        console.error('元素加载错误:', error);
        // 显示错误信息
        document.querySelector('#can-delete .elements-container').innerHTML = `
            <div class="text-center text-danger py-3">
                <i class="fas fa-exclamation-circle me-1"></i> 元素加载失败
            </div>
        `;
    }
}

// 初始化组内元素移动事件
function initGroupMoveEvents() {
    // 按钮移动事件
    document.querySelectorAll('.move-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const fromId = btn.dataset.from;
            const toId = btn.dataset.to;
            const groupIndex = fromId.split('-')[2]; // 从ID中提取组索引

            const fromContainer = document.querySelector(`#${fromId} .elements-container`);
            const toContainer = document.querySelector(`#${toId} .elements-container`);
            const selectedTags = fromContainer.querySelectorAll('.element-tag.selected');

            if (selectedTags.length === 0) {
                showAlert('请先选中要移动的元素');
                return;
            }

            selectedTags.forEach(tag => {
                tag.classList.remove('selected');
                tag.style.backgroundColor = '#f8f9fa';
                tag.style.color = 'inherit';
                toContainer.appendChild(tag);
            });

            // 更新当前组计数
            updateGroupBoxCounts(groupIndex);
        });
    });

    // 键盘快捷键（仅处理当前选中组的元素）
    document.addEventListener('keydown', (e) => {
        const selectedTags = document.querySelectorAll('.element-tag.selected');
        if (selectedTags.length === 0) return;

        const firstTag = selectedTags[0];
        const groupWrapper = firstTag.closest('.element-group-wrapper');
        if (!groupWrapper) return;
        const groupIndex = groupWrapper.dataset.groupIndex;

        const fromBox = firstTag.closest('.group-box');
        const fromId = fromBox.querySelector('.elements-container').parentElement.id;

        // 左箭头
        if (e.key === 'ArrowLeft') {
            let toId;
            if (fromId.includes('can-delete')) toId = `to-delete-${groupIndex}`;
            if (fromId.includes('must-keep')) toId = `can-delete-${groupIndex}`;
            
            if (toId) {
                e.preventDefault();
                moveSelectedElements(fromId, toId, groupIndex);
            }
        }

        // 右箭头
        if (e.key === 'ArrowRight') {
            let toId;
            if (fromId.includes('to-delete')) toId = `can-delete-${groupIndex}`;
            if (fromId.includes('can-delete')) toId = `must-keep-${groupIndex}`;
            
            if (toId) {
                e.preventDefault();
                moveSelectedElements(fromId, toId, groupIndex);
            }
        }
    });
}


// 初始化组内元素移动事件
function Step5initGroupMoveEvents() {
    // 按钮移动事件（仅处理两个框）
    document.querySelectorAll('.move-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const fromId = btn.dataset.from;
            const toId = btn.dataset.to;
            // 从ID中提取组索引（格式: to-delete-0 或 must-keep-0）
            const groupIndex = fromId.split('-')[2];

            const fromContainer = document.querySelector(`#${fromId} .elements-container`);
            const toContainer = document.querySelector(`#${toId} .elements-container`);
            
            // 检查容器是否存在
            if (!fromContainer || !toContainer) {
                console.error('移动失败：源容器或目标容器不存在');
                return;
            }

            const selectedTags = fromContainer.querySelectorAll('.element-tag.selected');

            if (selectedTags.length === 0) {
                showAlert('请先选中要移动的元素');
                return;
            }

            // 移动选中的元素
            selectedTags.forEach(tag => {
                tag.classList.remove('selected');
                tag.style.backgroundColor = '#f8f9fa';
                tag.style.color = 'inherit';
                toContainer.appendChild(tag);
            });

            // 更新当前组计数
            Step5updateGroupBoxCounts(groupIndex);
        });
    });

    // 键盘快捷键（仅处理两个框之间的移动）
    document.addEventListener('keydown', (e) => {
        const selectedTags = document.querySelectorAll('.element-tag.selected');
        if (selectedTags.length === 0) return;

        const firstTag = selectedTags[0];
        const groupWrapper = firstTag.closest('.element-group-wrapper');
        if (!groupWrapper) return;
        const groupIndex = groupWrapper.dataset.groupIndex;

        const fromBox = firstTag.closest('.group-box');
        const fromId = fromBox.id; // 直接获取框的ID（to-delete-x 或 must-keep-x）

        // 左箭头：从must-keep移动到to-delete
        if (e.key === 'ArrowLeft') {
            if (fromId.includes('must-keep')) {
                e.preventDefault();
                const toId = `to-delete-${groupIndex}`;
                Step5moveSelectedElements(fromId, toId, groupIndex);
            }
        }

        // 右箭头：从to-delete移动到must-keep
        if (e.key === 'ArrowRight') {
            if (fromId.includes('to-delete')) {
                e.preventDefault();
                const toId = `must-keep-${groupIndex}`;
                Step5moveSelectedElements(fromId, toId, groupIndex);
            }
        }
    });
}

// 移动选中元素（组内）
function moveSelectedElements(fromId, toId, groupIndex) {
    const fromContainer = document.querySelector(`#${fromId} .elements-container`);
    const toContainer = document.querySelector(`#${toId} .elements-container`);
    const selectedTags = fromContainer.querySelectorAll('.element-tag.selected');

    selectedTags.forEach(tag => {
        tag.classList.remove('selected');
        tag.style.backgroundColor = '#f8f9fa';
        tag.style.color = 'inherit';
        toContainer.appendChild(tag);
    });

    updateGroupBoxCounts(groupIndex);
}

// 更新组内三框计数
function updateGroupBoxCounts(groupIndex) {
    ['to-delete', 'can-delete', 'must-keep'].forEach(type => {
        const container = document.querySelector(`#${type}-${groupIndex} .elements-container`);
        const count = container.children.length;
        container.parentElement.querySelector('.element-count').textContent = count;
    });
}

// 移动选中元素（组内）
function Step5moveSelectedElements(fromId, toId, groupIndex) {
    const fromContainer = document.querySelector(`#${fromId} .elements-container`);
    const toContainer = document.querySelector(`#${toId} .elements-container`);
    
    if (!fromContainer || !toContainer) return;

    const selectedTags = fromContainer.querySelectorAll('.element-tag.selected');
    selectedTags.forEach(tag => {
        tag.classList.remove('selected');
        tag.style.backgroundColor = '#f8f9fa';
        tag.style.color = 'inherit';
        toContainer.appendChild(tag);
    });

    Step5updateGroupBoxCounts(groupIndex);
}

// 更新组内三框计数
function Step5updateGroupBoxCounts(groupIndex) {
    ['to-delete', 'must-keep'].forEach(type => {
        const container = document.querySelector(`#${type}-${groupIndex} .elements-container`);
        const count = container.children.length;
        container.parentElement.querySelector('.element-count').textContent = count;
    });
}


// 初始化应用过滤按钮事件
function initApplyFiltersEvent() {
    const applyBtn = document.getElementById('apply-filters');
    // 先移除可能存在的旧事件监听器
    const newApplyBtn = applyBtn.cloneNode(true);
    applyBtn.parentNode.replaceChild(newApplyBtn, applyBtn);
    
    newApplyBtn.addEventListener('click', async () => {
        const elementGroups = document.querySelectorAll('.element-group-wrapper');
        if (elementGroups.length === 0) {
            showAlert('请先加载元素组数据');
            return;
        }

        // 构建符合后端FilterSubmitRequest模型的数据结构
        const submitData = {
            selected_model: selectedModel || "",  // 匹配后端的selected_model字段
            analys: [],       // 对应"可以删除"的元素（待分析）
            need_del: [],     // 对应"确定删除"的元素
            fix: []           // 对应"必须保留"的元素
        };

        // 遍历每个元素组，按后端要求的字段收集数据
        elementGroups.forEach((group, groupIndex) => {
            // 1. 必须保留的元素 → 对应后端fix字段
            const retainElements = Array.from(
                document.querySelectorAll(`#must-keep-${groupIndex} .element-tag`)
            ).map(tag => tag.dataset.element || "").filter(Boolean);
            
            // 2. 可以删除的元素 → 对应后端analys字段
            const canDeleteElements = Array.from(
                document.querySelectorAll(`#can-delete-${groupIndex} .element-tag`)
            ).map(tag => tag.dataset.element || "").filter(Boolean);
            
            // 3. 确定删除的元素 → 对应后端need_del字段
            const deletedElements = Array.from(
                document.querySelectorAll(`#to-delete-${groupIndex} .element-tag`)
            ).map(tag => tag.dataset.element || "").filter(Boolean);

            // 按组添加到对应字段（保持与后端list[list[str]]结构一致）
            submitData.fix.push(retainElements);         // 必须保留 → fix
            submitData.analys.push(canDeleteElements);   // 可以删除 → analys
            submitData.need_del.push(deletedElements);   // 确定删除 → need_del
        });

        try {
            console.log("提交的数据结构（适配后端）:", submitData);

            const response = await fetch('/submit_filtered_elements', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken()
                },
                body: JSON.stringify(submitData)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                console.error("后端验证错误详情:", errorData);
                
                let errorMessage = '提交失败: ';
                if (Array.isArray(errorData.detail)) {
                    errorMessage += errorData.detail.map((msg, index) => 
                        `${index + 1}. ${msg}`
                    ).join('; ');
                } else if (errorData.detail || errorData.message) {
                    errorMessage += errorData.detail || errorData.message;
                } else if (errorData.errors) {
                    errorMessage += Object.entries(errorData.errors)
                        .map(([field, msg]) => `${field}: ${Array.isArray(msg) ? msg.join('; ') : msg}`)
                        .join('; ');
                } else {
                    errorMessage += `服务器返回 ${response.status} 错误`;
                }
                
                showAlert(errorMessage, 'error');
                return;
            }

            const result = await response.json();
            if (result.success) {
                showAlert('元素过滤已提交，开始计算');
                document.getElementById('step4-next').disabled = false;
            } else {
                showAlert('提交失败：' + result.message, 'error');
            }
        } catch (error) {
            showAlert('提交出错：' + error.message, 'error');
            console.error("请求异常:", error);
        }
    });
}

// 辅助函数：获取CSRF令牌（解决ReferenceError错误）
function getCSRFToken() {
    // 从cookie中获取csrftoken（适用于Django等框架）
    const cookieValue = document.cookie
        .split('; ')
        .find(row => row.startsWith('csrftoken='))
        ?.split('=')[1];
    return cookieValue || '';
}

// 初始化所有事件
function initAllEvents() {
    // 其他事件初始化...
    initModelConfirmEvent();
    Step5initModelConfirmEvent();
    initApplyFiltersEvent();
    Step5initApplyFiltersEvent()
}

// 初始化应用过滤按钮事件
function Step5initApplyFiltersEvent() {
    const exportBtn = document.getElementById('export-model');
    // 先移除可能存在的旧事件监听器
    const newExportBtn = exportBtn.cloneNode(true);
    exportBtn.parentNode.replaceChild(newExportBtn, exportBtn);
    
    newExportBtn.addEventListener('click', async () => {
        // 验证是否选择了模型
        if (!selectedModel) {
            showAlert('请先选择并确认模型', 'warning');
            return;
        }
        
        // 验证是否有元素组数据
        const elementGroups = document.querySelectorAll('.element-group-wrapper');
        if (elementGroups.length === 0) {
            showAlert('请先加载并处理元素组数据', 'warning');
            return;
        }

        // 构建符合后端要求的数据结构
        const exportData = {
            output_path: document.getElementById('output-path').value.trim() || './output/models/',
            selected_model: getSelectedModelDetails() || {},
            element_groups: [],
            include_metrics: document.getElementById('include-metrics').checked,
            file_format: 'tdb'
        };

        // 收集每个组的两框选择内容
        elementGroups.forEach((group, groupIndex) => {
            // 只收集"必须保留的元素"组成子列表
            const mustKeepElements = Array.from(
                document.querySelectorAll(`#must-keep-${groupIndex} .element-tag`)
            ).map(tag => tag.textContent.trim() || "").filter(Boolean);
            
            // 每个组对应一个子列表，整体组成 list[list[str]]
            exportData.element_groups.push(mustKeepElements);
        });

        try {
            console.log("提交的导出数据:", exportData);
            
            // 显示加载状态
            newExportBtn.disabled = true;
            newExportBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> 正在导出...';

            const response = await fetch('/tdb_generate_model_assessed', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken()
                },
                body: JSON.stringify(exportData)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                console.error("导出错误详情:", errorData);
                
                let errorMessage = '导出失败: ';
                if (Array.isArray(errorData.detail)) {
                    errorMessage += errorData.detail.map((msg, index) => 
                        `${index + 1}. ${msg}`
                    ).join('; ');
                } else if (errorData.detail || errorData.message) {
                    errorMessage += errorData.detail || errorData.message;
                } else if (errorData.errors) {
                    errorMessage += Object.entries(errorData.errors)
                        .map(([field, msg]) => `${field}: ${Array.isArray(msg) ? msg.join('; ') : msg}`)
                        .join('; ');
                } else {
                    errorMessage += `服务器返回 ${response.status} 错误`;
                }
                
                showAlert(errorMessage, 'error');
                return;
            }

            const result = await response.json();
            if (result.success) {
                showAlert('模型导出成功！', 'success');
                // 处理下载链接
                if (result.download_url) {
                    window.open(result.download_url, '_blank');
                }
            } else {
                showAlert('导出失败：' + (result.message || '未知错误'), 'error');
            }
        } catch (error) {
            showAlert('导出过程出错：' + error.message, 'error');
            console.error("导出请求异常:", error);
        } finally {
            // 恢复按钮状态
            newExportBtn.disabled = false;
            newExportBtn.innerHTML = '<i class="fas fa-download me-1"></i> 导出选中模型';
        }
    });
}

// 获取选中模型的详细信息（根据实际情况调整）
function getSelectedModelDetails() {
    // 这里可以返回更详细的模型信息，根据你的数据结构调整
    return {
        model_name: selectedModel,
        // 可添加其他模型相关字段
    };
}

/**
 * 创建单个元素标签
 */
function createElementTag(element) {
    const tag = document.createElement('div');
    tag.className = 'element-tag';
    tag.dataset.element = element;
    tag.textContent = element;
    tag.addEventListener('click', () => {
        tag.classList.toggle('selected');
        tag.style.backgroundColor = tag.classList.contains('selected') 
            ? '#3B82F6' 
            : '#f8f9fa';
        tag.style.color = tag.classList.contains('selected') ? 'white' : 'inherit';
    });
    return tag;
}
/**
 * 添加元素移动事件监听器
 */
function addElementMoveEventListeners() {
    // 移动按钮点击事件
    document.querySelectorAll('.move-btn').forEach(button => {
        button.addEventListener('click', function() {
            const fromId = this.dataset.from;
            const toId = this.dataset.to;
            
            moveSelectedElements(fromId, toId);
        });
    });
    
    // 添加键盘快捷键支持（左右箭头）
    document.addEventListener('keydown', function(e) {
        // 只在有选中元素时处理
        const selectedElements = document.querySelectorAll('.element-tag.selected');
        if (selectedElements.length === 0) return;
        
        // 获取第一个选中元素所在的容器ID
        const firstSelected = selectedElements[0];
        const fromContainer = firstSelected.closest('.element-group-box');
        if (!fromContainer) return;
        const fromId = fromContainer.id;
        
        // 左箭头
        if (e.key === 'ArrowLeft') {
            let toId;
            if (fromId === 'can-delete') toId = 'to-delete';
            else if (fromId === 'must-keep') toId = 'can-delete';
            
            if (toId) {
                e.preventDefault();
                moveSelectedElements(fromId, toId);
            }
        } 
        // 右箭头
        else if (e.key === 'ArrowRight') {
            let toId;
            if (fromId === 'to-delete') toId = 'can-delete';
            else if (fromId === 'can-delete') toId = 'must-keep';
            
            if (toId) {
                e.preventDefault();
                moveSelectedElements(fromId, toId);
            }
        }
    });
}


/**
 * 移动选中的元素从一个容器到另一个容器
 */
function moveSelectedElements(fromId, toId) {
    const fromContainer = document.querySelector(`#${fromId} .elements-container`);
    const toContainer = document.querySelector(`#${toId} .elements-container`);
    
    if (!fromContainer || !toContainer) return;
    
    // 获取所有选中的元素
    const selectedElements = fromContainer.querySelectorAll('.element-tag.selected');
    if (selectedElements.length === 0) {
        showAlert('请先选择要移动的元素');
        return;
    }
    
    // 移动元素
    selectedElements.forEach(element => {
        // 移除选中状态
        element.classList.remove('selected');
        element.style.backgroundColor = '#e9ecef';
        element.style.color = 'inherit';
        
        // 移动到目标容器
        toContainer.appendChild(element);
    });
    
    // 更新计数
    updateElementCounts();
}

/**
 * 更新每个容器中的元素计数
 */
function updateElementCounts() {
    document.querySelectorAll('.element-group-box').forEach(box => {
        const count = box.querySelectorAll('.element-tag').length;
        box.querySelector('.element-count').textContent = count;
    });
}


/**
 * 创建单个元素分类框
 */
function createElementGroupBox(config) {
    const groupBox = document.createElement('div');
    groupBox.id = config.id;
    groupBox.className = `element-group-box element-group-${config.class}`;
    groupBox.style.flex = '1';
    groupBox.style.minWidth = '250px';
    groupBox.style.marginBottom = '1rem';
    groupBox.style.padding = '0.8rem';
    groupBox.style.border = '1px solid #dee2e6';
    groupBox.style.borderRadius = '4px';
    
    // 标题栏
    const titleBar = document.createElement('div');
    titleBar.className = 'element-group-title';
    titleBar.style.marginBottom = '0.8rem';
    titleBar.style.display = 'flex';
    titleBar.style.alignItems = 'center';
    titleBar.style.justifyContent = 'space-between';
    titleBar.innerHTML = `
        <div>
            <i class="fas fa-${config.icon} me-2"></i>
            <span style="font-weight: 500;">${config.title}</span>
            <span class="element-count badge ms-2" style="font-size: 0.7rem;">0</span>
        </div>
    `;
    
    // 元素容器
    const elementsContainer = document.createElement('div');
    elementsContainer.className = 'elements-container';
    elementsContainer.style.minHeight = '150px';
    elementsContainer.style.maxHeight = '300px';
    elementsContainer.style.overflowY = 'auto';
    elementsContainer.style.padding = '0.5rem';
    elementsContainer.style.border = '1px dashed #ced4da';
    elementsContainer.style.borderRadius = '4px';
    elementsContainer.style.backgroundColor = '#f9f9f9';
    
    // 移动按钮区域
    const buttonContainer = document.createElement('div');
    buttonContainer.className = 'element-move-buttons';
    buttonContainer.style.display = 'flex';
    buttonContainer.style.justifyContent = 'center';
    buttonContainer.style.gap = '0.5rem';
    buttonContainer.style.marginTop = '0.8rem';
    
    // 根据位置决定显示哪些移动按钮
    if (config.id === 'to-delete') {
        // 只能向右移动
        buttonContainer.innerHTML = `
            <button class="move-btn move-right btn btn-sm btn-outline-secondary" 
                    data-from="${config.id}" data-to="can-delete">
                <i class="fas fa-chevron-right"></i>
            </button>
        `;
    } else if (config.id === 'can-delete') {
        // 可以向左和向右移动
        buttonContainer.innerHTML = `
            <button class="move-btn move-left btn btn-sm btn-outline-secondary" 
                    data-from="${config.id}" data-to="to-delete">
                <i class="fas fa-chevron-left"></i>
            </button>
            <button class="move-btn move-right btn btn-sm btn-outline-secondary" 
                    data-from="${config.id}" data-to="must-keep">
                <i class="fas fa-chevron-right"></i>
            </button>
        `;
    } else if (config.id === 'must-keep') {
        // 只能向左移动
        buttonContainer.innerHTML = `
            <button class="move-btn move-left btn btn-sm btn-outline-secondary" 
                    data-from="${config.id}" data-to="can-delete">
                <i class="fas fa-chevron-left"></i>
            </button>
        `;
    }
    
    // 组装
    groupBox.appendChild(titleBar);
    groupBox.appendChild(elementsContainer);
    groupBox.appendChild(buttonContainer);
    
    return groupBox;
}



/**
 * 向后端请求元素二维列表，动态生成元素组小框
 * 后端返回格式：[['H','He','Li'], ['Li','Be','C'], ...]
 */
async function fetchAndRenderElementGroups() {
    const elementContainer = document.getElementById('element-groups-container');
    // 清空容器（清除加载提示）
    elementContainer.innerHTML = '';

    try {
        // 1. 向后端发送请求（需后端提供/get_element_groups接口）
        const response = await fetch('/get_element_groups', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            // 可选：传递选中的模型，后端按模型返回对应元素组
            body: JSON.stringify({ selected_model: selectedModel || '' })
        });

        if (!response.ok) {
            throw new Error(`请求失败：${response.status} ${response.statusText}`);
        }

        const result = await response.json();
        if (!result.success || !Array.isArray(result.element_groups)) {
            throw new Error('后端未返回有效元素组数据');
        }

        const elementGroups = result.element_groups;
        // 2. 处理无元素组的情况
        if (elementGroups.length === 0) {
            elementContainer.innerHTML = `
                <div class="text-center text-muted py-3">
                    <i class="fas fa-info-circle me-1"></i> 暂无元素组数据
                </div>
            `;
            return;
        }

        // 3. 循环元素组，生成每个小框
        elementGroups.forEach((elementList, groupIndex) => {
            // 跳过空元素组
            if (!Array.isArray(elementList) || elementList.length === 0) return;

            // 3.1 创建元素组小框容器
            const groupBox = document.createElement('div');
            groupBox.className = 'element-group-box';
            groupBox.style.marginBottom = '1rem';
            groupBox.style.padding = '0.8rem';
            groupBox.style.border = '1px solid #dee2e6';
            groupBox.style.borderRadius = '4px';
            groupBox.style.backgroundColor = '#f8f9fa';

            // 3.2 小框标题（组1、组2...）
            const groupTitle = document.createElement('div');
            groupTitle.className = 'element-group-title';
            groupTitle.style.marginBottom = '0.5rem';
            groupTitle.style.fontWeight = '500';
            groupTitle.style.fontSize = '0.9rem';
            groupTitle.textContent = `组${groupIndex + 1}`;

            // 3.3 元素标签容器（复用原有element-selector样式）
            const groupElementsContainer = document.createElement('div');
            groupElementsContainer.className = 'element-selector';
            groupElementsContainer.style.flexWrap = 'wrap';
            groupElementsContainer.style.gap = '0.5rem';

            // 3.4 生成组内每个元素标签（复用原有element-tag样式）
            elementList.forEach(element => {
                const elementTag = document.createElement('div');
                elementTag.className = 'element-tag';
                elementTag.style.padding = '0.3rem 0.6rem';
                elementTag.style.borderRadius = '20px';
                elementTag.style.backgroundColor = '#e9ecef';
                elementTag.style.cursor = 'pointer';
                elementTag.style.display = 'inline-flex';
                elementTag.style.alignItems = 'center';
                elementTag.style.gap = '0.3rem';
                elementTag.innerHTML = `
                    ${element} 
                    <span class="remove-btn"><i class="fas fa-times"></i></span>
                `;

                // 3.5 绑定元素标签删除事件（点击×删除标签）
                elementTag.querySelector('.remove-btn').addEventListener('click', (e) => {
                    e.stopPropagation(); // 阻止事件冒泡（避免触发小框其他事件）
                    elementTag.remove();
                });

                // 3.6 绑定元素标签选中事件（点击标签高亮，用于批量删除）
                elementTag.addEventListener('click', () => {
                    elementTag.classList.toggle('selected');
                    // 选中样式：可自定义（如背景色变红色）
                    elementTag.style.backgroundColor = elementTag.classList.contains('selected') 
                        ? '#ffcdd2' 
                        : '#e9ecef';
                });

                groupElementsContainer.appendChild(elementTag);
            });

            // 3.7 组装小框（标题+元素标签）
            groupBox.appendChild(groupTitle);
            groupBox.appendChild(groupElementsContainer);
            elementContainer.appendChild(groupBox);
        });

    } catch (error) {
        // 4. 处理请求错误
        elementContainer.innerHTML = `
            <div class="text-center text-danger py-3">
                <i class="fas fa-exclamation-circle me-1"></i> 元素组加载失败：${error.message}
            </div>
        `;
        console.error('元素组加载错误:', error);
    }
}

// 初始化事件监听器
function initEventListeners() {
    // 流程步骤点击事件
    document.querySelectorAll('.flow-step').forEach(step => {
        step.addEventListener('click', function() {
            const stepNum = parseInt(this.dataset.step);
            // 只允许导航到已完成或当前步骤
            if (isStepAccessible(stepNum)) {
                navigateToStep(stepNum);
                // 如果导航到步骤3，检查是否有缓存图片并加载CSV数据
                if (stepNum === 3) {
                    checkAndDisplayCachedPlot();
                    loadCSVData();
                }
            }
        });
    });
    
    // 步骤导航按钮
    document.getElementById('step2-prev').addEventListener('click', () => navigateToStep(1));
    document.getElementById('step3-prev').addEventListener('click', () => navigateToStep(2));
    document.getElementById('step4-prev').addEventListener('click', () => {
        navigateToStep(3);
        checkAndDisplayCachedPlot();
        loadCSVData();
    });
    document.getElementById('step4-next').addEventListener('click', () => navigateToStep(5));
    document.getElementById('step5-prev').addEventListener('click', () => {
        // 根据之前的步骤决定返回哪里
        const lastStep = localStorage.getItem('lastStep') || 3;
        navigateToStep(parseInt(lastStep));
        if (parseInt(lastStep) === 3) {
            checkAndDisplayCachedPlot();
            loadCSVData();
        }
    });
    
    // // 导出模型按钮
    // document.getElementById('export-model').addEventListener('click', function() {
    //     if (selectedModel) {
    //         showAlert(`模型 ${selectedModel} 已成功导出！`);
    //     } else {
    //         alert('请先选择一个模型');
    //     }
    // });
    
    // 模型选择事件
    document.querySelectorAll('.model-card').forEach(card => {
        card.addEventListener('click', function() {
            // 清除同组中其他卡片的选中状态
            const parent = this.parentElement;
            parent.querySelectorAll('.model-card').forEach(c => {
                c.classList.remove('selected');
            });
            
            // 设置当前卡片为选中状态
            this.classList.add('selected');
            selectedModel = this.dataset.model;
        });
    });

    
    // 元素标签点击事件
    document.querySelectorAll('.element-tag').forEach(tag => {
        tag.addEventListener('click', function(e) {
            // 如果点击的是删除按钮，则移除标签
            if (e.target.closest('.remove-btn')) {
                this.remove();
            } else {
                // 否则切换选中状态
                this.classList.toggle('selected');
            }
        });
    });
    
    // 应用元素过滤按钮
    initModelConfirmEvent();
    Step5initModelConfirmEvent();
    initApplyFiltersEvent();
    Step5initApplyFiltersEvent();
}

// 导航到指定步骤
function navigateToStep(stepNum) {
    localStorage.setItem('lastStep', currentStep);
    currentStep = stepNum;

    // 显示当前步骤内容
    document.querySelectorAll('.content-section').forEach(section => {
        section.classList.remove('active');
    });
    document.getElementById(`section-${stepNum}`).classList.add('active');

    // 步骤4：初始化模型选择和元素管理
    if (stepNum === 4) {
        renderModelCardsFromCSV(); // 渲染模型卡片
        initModelConfirmEvent();   // 初始化模型确认事件（核心新增）
        document.getElementById('step4-next').disabled = true; // 初始禁用下一步
    }

    // 步骤3：加载CSV数据（原有逻辑不变）
    if (stepNum === 3) {
        checkAndDisplayCachedPlot();
        loadCSVData().then(() => {
            console.log('步骤3 CSV加载完成');
        });
    }

    if (stepNum === 5) {
        Step5renderModelCardsFromCSV(); // 渲染模型卡片
        Step5initModelConfirmEvent();
        document.getElementById('export-model').disabled = true; // 初始禁用下一步
    }

    // 更新步骤状态和进度条（原有逻辑不变）
    document.querySelectorAll('.flow-step').forEach(step => {
        const stepNumber = parseInt(step.dataset.step);
        step.classList.remove('active', 'completed');
        if (stepNumber === stepNum) step.classList.add('active');
        else if (stepNumber < stepNum) step.classList.add('completed');
    });
    updateProgressBar();
}

// 更新进度条
function updateProgressBar() {
    const progress = ((currentStep - 1) / (totalSteps - 1)) * 100;
    document.getElementById('connector-progress').style.width = `${progress}%`;
}

// 检查步骤是否可访问
function isStepAccessible(stepNum) {
    // 1-2-3-4-5的流程，同时允许1-2-3直接到5
    if (stepNum <= currentStep) return true;
    if (currentStep >= 3 && stepNum === 5) return true;
    return false;
}

// 显示提示消息
function showAlert(message) {
    const alertElement = document.getElementById('alert-message');
    document.getElementById('alert-text').textContent = message;
    alertElement.className = 'alert alert-success alert-custom';
    alertElement.style.display = 'block';
    
    // 3秒后自动隐藏
    setTimeout(() => {
        alertElement.style.display = 'none';
    }, 3000);
}

// 显示错误消息
function showError(message) {
    const alertElement = document.getElementById('alert-message');
    document.getElementById('alert-text').textContent = message;
    alertElement.className = 'alert alert-danger alert-custom';
    alertElement.style.display = 'block';
    
    // 5秒后自动隐藏
    setTimeout(() => {
        alertElement.style.display = 'none';
    }, 5000);
}

// 辅助函数：格式化文件大小
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 辅助函数：生成不同的颜色
function getColor(index) {
    const colors = [
        '#3B82F6', '#10B981', '#EF4444', '#F59E0B', 
        '#8B5CF6', '#EC4899', '#06B6D4', '#64748B'
    ];
    return colors[index % colors.length];
}

// 模拟调用ALRunner中的output_tdb_file函数
function outputTdbFile(user, mask, recordPath = '') {
    try {
        // 这里模拟函数调用
        console.log(`调用output_tdb_file: user=${user}, mask=${mask}, recordPath=${recordPath}`);
        
        // 模拟生成文件路径
        const filePath = `./records/tdb_file_${user}_${mask}.tdb`;
        console.log(`TDB文件生成成功: ${filePath}`);
        
        return true;
    } catch (e) {
        console.error(`输出TDB文件失败: ${e}`);
        return false;
    }
}
