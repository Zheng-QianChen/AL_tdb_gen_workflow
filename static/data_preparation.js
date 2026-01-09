

// 定义各模型的超参数配置
const modelHyperParameters = {
    'gbr': {
        'n_estimators': {
            type: 'number',
            label: '树的数量',
            value: 100,
            min: 10,
            max: 1000,
            step: 10,
            help: '集成中树的数量，增加通常能提高性能但增加计算成本'
        },
        'learning_rate': {
            type: 'number',
            label: '学习率',
            value: 0.1,
            min: 0.001,
            max: 1,
            step: 0.001,
            help: '每个树的贡献权重缩减因子'
        },
        'max_depth': {
            type: 'number',
            label: '最大深度',
            value: 3,
            min: 1,
            max: 20,
            step: 1,
            help: '树的最大深度，控制过拟合'
        },
        'subsample': {
            type: 'number',
            label: '子样本比例',
            value: 1.0,
            min: 0.1,
            max: 1,
            step: 0.1,
            help: '每棵树的训练样本比例'
        }
    },
    'rf': {
        'n_estimators': {
            type: 'number',
            label: '树的数量',
            value: 100,
            min: 10,
            max: 1000,
            step: 10,
            help: '森林中树的数量'
        },
        'max_depth': {
            type: 'number',
            label: '最大深度',
            value: null,
            min: 1,
            max: 50,
            step: 1,
            help: '树的最大深度，null表示无限制'
        },
        'min_samples_split': {
            type: 'number',
            label: '最小分裂样本数',
            value: 2,
            min: 2,
            max: 100,
            step: 1,
            help: '分裂内部节点所需的最小样本数'
        },
        'max_features': {
            type: 'select',
            label: '最大特征数',
            value: 'sqrt',
            options: [
                { value: 'sqrt', label: '平方根 (sqrt)' },
                { value: 'log2', label: '对数2 (log2)' },
                { value: null, label: '全部特征 (None)' }
            ],
            help: '寻找最佳分裂时考虑的特征数量'
        }
    },
    'lr': {
        'fit_intercept': {
            type: 'checkbox',
            label: '拟合截距',
            value: true,
            help: '是否计算该模型的截距'
        },
        'normalize': {
            type: 'checkbox',
            label: '归一化',
            value: false,
            help: '是否在回归前对特征进行归一化'
        },
        'copy_X': {
            type: 'checkbox',
            label: '复制X',
            value: true,
            help: '是否复制X而不是覆盖'
        }
    },
    'ridge': {
        'alpha': {
            type: 'number',
            label: '正则化强度',
            value: 1.0,
            min: 0.001,
            max: 10,
            step: 0.001,
            help: '正则化强度，值越大正则化越强'
        },
        'fit_intercept': {
            type: 'checkbox',
            label: '拟合截距',
            value: true,
            help: '是否计算该模型的截距'
        },
        'normalize': {
            type: 'checkbox',
            label: '归一化',
            value: false,
            help: '是否在回归前对特征进行归一化'
        },
        'solver': {
            type: 'select',
            label: '求解器',
            value: 'auto',
            options: [
                { value: 'auto', label: '自动选择' },
                { value: 'svd', label: '奇异值分解' },
                { value: 'cholesky', label: 'Cholesky分解' },
                { value: 'lsqr', label: '最小二乘QR' },
                { value: 'sparse_cg', label: '共轭梯度' },
                { value: 'sag', label: '随机平均梯度下降' }
            ],
            help: '用于求解的算法'
        }
    },
    'lasso': {
        'alpha': {
            type: 'number',
            label: '正则化强度',
            value: 1.0,
            min: 0.001,
            max: 10,
            step: 0.001,
            help: '正则化强度，值越大正则化越强'
        },
        'fit_intercept': {
            type: 'checkbox',
            label: '拟合截距',
            value: true,
            help: '是否计算该模型的截距'
        },
        'normalize': {
            type: 'checkbox',
            label: '归一化',
            value: false,
            help: '是否在回归前对特征进行归一化'
        },
        'max_iter': {
            type: 'number',
            label: '最大迭代次数',
            value: 1000,
            min: 100,
            max: 10000,
            step: 100,
            help: '最大迭代次数'
        }
    },
    'knn': {
        'n_neighbors': {
            type: 'number',
            label: '近邻数量',
            value: 5,
            min: 1,
            max: 50,
            step: 1,
            help: '用于预测的近邻数量'
        },
        'weights': {
            type: 'select',
            label: '权重计算方式',
            value: 'uniform',
            options: [
                { value: 'uniform', label: '均匀权重' },
                { value: 'distance', label: '距离权重' }
            ],
            help: '预测中使用的权重函数'
        },
        'algorithm': {
            type: 'select',
            label: '算法',
            value: 'auto',
            options: [
                { value: 'auto', label: '自动选择' },
                { value: 'ball_tree', label: '球树' },
                { value: 'kd_tree', label: 'KD树' },
                { value: 'brute', label: '暴力搜索' }
            ],
            help: '用于计算最近邻的算法'
        },
        'leaf_size': {
            type: 'number',
            label: '叶节点大小',
            value: 30,
            min: 10,
            max: 100,
            step: 1,
            help: '球树或KD树的叶节点大小'
        }
    },
    'svr': {
        'kernel': {
            type: 'select',
            label: '核函数',
            value: 'rbf',
            options: [
                { value: 'linear', label: '线性' },
                { value: 'poly', label: '多项式' },
                { value: 'rbf', label: '径向基' },
                { value: 'sigmoid', label: 'Sigmoid' }
            ],
            help: '核函数类型'
        },
        'C': {
            type: 'number',
            label: '正则化参数',
            value: 1.0,
            min: 0.001,
            max: 100,
            step: 0.001,
            help: '正则化参数，较小的C值表示更强的正则化'
        },
        'gamma': {
            type: 'select',
            label: '核系数',
            value: 'scale',
            options: [
                { value: 'scale', label: '1/(n_features * X.var())' },
                { value: 'auto', label: '1/n_features' },
                { value: 0.1, label: '0.1' },
                { value: 1, label: '1' },
                { value: 10, label: '10' }
            ],
            help: 'rbf, poly和sigmoid的核系数'
        },
        'epsilon': {
            type: 'number',
            label: '不敏感区域',
            value: 0.1,
            min: 0.01,
            max: 1,
            step: 0.01,
            help: '不惩罚的训练样本的epsilon-tube'
        }
    },
    'mlp': {
        'hidden_layer_sizes': {
            type: 'text',
            label: '隐藏层大小',
            value: '(100,)',
            help: '隐藏层神经元数量，例如(100,)表示一个100神经元的层，(50,50)表示两个50神经元的层'
        },
        'activation': {
            type: 'select',
            label: '激活函数',
            value: 'relu',
            options: [
                { value: 'identity', label: '线性' },
                { value: 'logistic', label: '逻辑斯蒂(sigmoid)' },
                { value: 'tanh', label: '双曲正切' },
                { value: 'relu', label: 'ReLU' }
            ],
            help: '隐藏层的激活函数'
        },
        'solver': {
            type: 'select',
            label: '求解器',
            value: 'adam',
            options: [
                { value: 'lbfgs', label: 'L-BFGS' },
                { value: 'sgd', label: '随机梯度下降' },
                { value: 'adam', label: 'Adam' }
            ],
            help: '权重优化的求解器'
        },
        'alpha': {
            type: 'number',
            label: 'L2惩罚系数',
            value: 0.0001,
            min: 0.00001,
            max: 0.1,
            step: 0.00001,
            help: 'L2正则化项的参数'
        },
        'learning_rate': {
            type: 'select',
            label: '学习率调度',
            value: 'constant',
            options: [
                { value: 'constant', label: '常数' },
                { value: 'invscaling', label: '逆缩放' },
                { value: 'adaptive', label: '自适应' }
            ],
            help: '学习率调度'
        }
    },
    'dt': {
        'max_depth': {
            type: 'number',
            label: '最大深度',
            value: null,
            min: 1,
            max: 50,
            step: 1,
            help: '树的最大深度，控制过拟合'
        },
        'min_samples_split': {
            type: 'number',
            label: '最小分裂样本数',
            value: 2,
            min: 2,
            max: 100,
            step: 1,
            help: '分裂内部节点所需的最小样本数'
        },
        'min_samples_leaf': {
            type: 'number',
            label: '叶节点最小样本数',
            value: 1,
            min: 1,
            max: 100,
            step: 1,
            help: '叶节点所需的最小样本数'
        },
        'max_features': {
            type: 'select',
            label: '最大特征数',
            value: null,
            options: [
                { value: 'sqrt', label: '平方根 (sqrt)' },
                { value: 'log2', label: '对数2 (log2)' }
            ],
            help: '寻找最佳分裂时考虑的特征数量'
        }
    },
    'xgb': {
        'n_estimators': {
            type: 'number',
            label: '树的数量',
            value: 100,
            min: 10,
            max: 1000,
            step: 10,
            help: '树的数量'
        },
        'learning_rate': {
            type: 'number',
            label: '学习率',
            value: 0.1,
            min: 0.001,
            max: 1,
            step: 0.001,
            help: '学习率'
        },
        'max_depth': {
            type: 'number',
            label: '最大深度',
            value: 3,
            min: 1,
            max: 20,
            step: 1,
            help: '树的最大深度'
        },
        'subsample': {
            type: 'number',
            label: '子样本比例',
            value: 1.0,
            min: 0.1,
            max: 1,
            step: 0.1,
            help: '每棵树的训练样本比例'
        },
        'objective': {
            type: 'select',
            label: '目标函数',
            value: 'reg:squarederror',
            options: [
                { value: 'reg:squarederror', label: '平方误差回归' },
                { value: 'reg:squaredlogerror', label: '平方对数误差回归' },
                { value: 'reg:pseudohubererror', label: '伪Huber误差回归' }
            ],
            help: '学习目标和相应的学习任务'
        }
    },
    'catboost': {
        'iterations': {
            type: 'number',
            label: '迭代次数',
            value: 1000,
            min: 100,
            max: 10000,
            step: 100,
            help: '训练的树的数量，值越大模型能力越强但可能过拟合'
        },
        'learning_rate': {
            type: 'number',
            label: '学习率',
            value: 0.03,
            min: 0.001,
            max: 0.3,
            step: 0.001,
            help: '每次迭代的步长，较小的值需要更多迭代次数'
        },
        'depth': {
            type: 'number',
            label: '树深度',
            value: 6,
            min: 3,
            max: 12,
            step: 1,
            help: '每棵树的深度，控制单棵树的复杂度'
        },
        'l2_leaf_reg': {
            type: 'number',
            label: '叶节点L2正则化',
            value: 3,
            min: 0.1,
            max: 10,
            step: 0.1,
            help: '叶节点权重的L2正则化系数，值越大正则化越强'
        },
        'subsample': {
            type: 'number',
            label: '样本采样比例',
            value: 1.0,
            min: 0.5,
            max: 1.0,
            step: 0.1,
            help: '每次迭代使用的样本比例，用于防止过拟合'
        },
        'one_hot_max_size': {
            type: 'number',
            label: '独热编码阈值',
            value: 5,
            min: 2,
            max: 20,
            step: 1,
            help: '类别数小于等于该值的特征使用独热编码'
        },
        'verbose': {
            type: 'number',
            label: '日志输出频率',
            value: 100,
            min: 0,
            max: 1000,
            step: 10,
            help: '每N轮输出一次日志，0表示不输出'
        },
        'early_stopping_rounds': {
            type: 'number',
            label: '早停轮数',
            value: 50,
            min: 0,
            max: 500,
            step: 10,
            help: '验证集性能未提升的轮数达到此值则停止训练，0表示不启用'
        },
        'task_type': {
            type: 'select',
            label: '计算设备',
            value: 'CPU',
            options: [
                { label: 'CPU', value: 'CPU' },
                { label: 'GPU', value: 'GPU' }
            ],
            help: '选择训练使用的计算设备'
        }
    }
};

function safeApplyTranslation() {
    // 使用 setTimeout 确保在当前 DOM 渲染任务完成后执行
    setTimeout(() => {
        if (typeof window.updatePageContent === 'function') {
            const currentLang = localStorage.getItem('preferredLang') || 'en';
            window.updatePageContent(currentLang);
        } else {
            console.warn("翻译插件尚未就绪，将在 100ms 后重试...");
            setTimeout(safeApplyTranslation, 100);
        }
    }, 0);
}

function updateHyperParametersJson() {
    const params = {};
    // 遍历所有超参数输入控件
    document.querySelectorAll('.hyper-param').forEach(input => {
        const paramName = input.dataset.name;
        let value;
        
        // 根据控件类型获取不同的取值
        switch (input.type) {
            case 'checkbox':
                value = input.checked;
                break;
            case 'number':
                value = input.value ? (input.step.includes('.') ? parseFloat(input.value) : parseInt(input.value)) : null;
                break;
            case 'select':
                value = input.value === 'null' ? null : input.value;
                if (!isNaN(value)) value = Number(value);
                break;
            default:
                value = input.value;
        }
        
        params[paramName] = value;
    });
    
    // 将参数对象转换为JSON字符串并存储
    document.getElementById('ml-hyper-parameters-json').value = JSON.stringify(params);
}


function generateHyperParameters(modelName) {
    const container = document.getElementById('hyper-params-container');
    container.innerHTML = '';  // 清空容器
    
    // 获取选中模型的超参数配置
    const params = modelHyperParameters[modelName] || {};
    
    // 如果没有超参数配置，显示提示信息
    if (Object.keys(params).length === 0) {
        container.innerHTML = '<div class="text-muted">该模型没有可配置的超参数</div>';
        updateHyperParametersJson();
        return;
    }
    
    // 为每个超参数生成对应的表单控件
    Object.keys(params).forEach(paramName => {
        const paramConfig = params[paramName];
        const paramItem = document.createElement('div');
        paramItem.className = 'hyper-param-item';
        paramItem.dataset.param = paramName;
        
        let inputHtml = '';
        
        // 根据参数类型生成不同的输入控件
        switch (paramConfig.type) {
            case 'number':
                inputHtml = `
                    <input type="number" class="form-control hyper-param" 
                        data-name="${paramName}"
                        value="${paramConfig.value !== null ? paramConfig.value : ''}"
                        ${paramConfig.min !== undefined ? `min="${paramConfig.min}"` : ''}
                        ${paramConfig.max !== undefined ? `max="${paramConfig.max}"` : ''}
                        ${paramConfig.step !== undefined ? `step="${paramConfig.step}"` : ''}>
                `;
                break;
                
            case 'text':
                inputHtml = `
                    <input type="text" class="form-control hyper-param" 
                        data-name="${paramName}"
                        value="${paramConfig.value}">
                `;
                break;
                
            case 'checkbox':
                inputHtml = `
                    <div class="form-check form-switch">
                        <input class="form-check-input hyper-param" type="checkbox" 
                            data-name="${paramName}"
                            ${paramConfig.value ? 'checked' : ''}>
                    </div>
                `;
                break;
                
            case 'select':
                inputHtml = `<select class="form-select hyper-param" data-name="${paramName}">`;
                paramConfig.options.forEach(option => {
                    inputHtml += `
                        <option value="${option.value}" ${paramConfig.value == option.value ? 'selected' : ''}>
                            ${option.label}
                        </option>
                    `;
                });
                inputHtml += `</select>`;
                break;
        }
        
        // 组装完整的参数项HTML
        paramItem.innerHTML = `
            <label class="form-label">${paramConfig.label} (${paramName})</label>
            ${inputHtml}
            <div class="form-text">${paramConfig.help}</div>
        `;
        
        container.appendChild(paramItem);
        
        // 添加事件监听，参数变化时更新JSON
        paramItem.querySelector('.hyper-param').addEventListener('change', updateHyperParametersJson);
    });
    
    // 初始化JSON字符串
    updateHyperParametersJson();
}

// 路径验证函数
function validatePath(path, isFile = false) {
    // 基本路径验证正则表达式
    // 允许字母、数字、斜杠、点、下划线和连字符
    const pathRegex = /^[a-zA-Z0-9_\/\-.]+$/;
    
    // 检查是否为空
    if (!path.trim()) return false;
    
    // 检查是否包含无效字符
    if (!pathRegex.test(path)) return false;
    
    // 检查文件路径是否有扩展名（如果是文件）
    if (isFile) {
        const hasExtension = /\.[a-zA-Z0-9]+$/.test(path);
        if (!hasExtension) return false;
    }
    
    // 检查是否有连续的斜杠
    if (path.includes('//')) return false;
    
    return true;
}

// 路径输入验证处理
function setupPathValidation() {
    const pathInputs = document.querySelectorAll('.path-input');
    
    pathInputs.forEach(input => {
        // 确定是否为文件路径（有ID包含"file"）
        const isFilePath = input.id.includes('file');
        
        // 实时验证
        input.addEventListener('input', function() {
            const isValid = validatePath(this.value, isFilePath);
            
            if (isValid) {
                this.classList.remove('is-invalid');
                this.classList.add('is-valid');
            } else {
                this.classList.remove('is-valid');
                this.classList.add('is-invalid');
            }
        });
        
        // 失去焦点时验证
        input.addEventListener('blur', function() {
            const isValid = validatePath(this.value, isFilePath);
            
            if (!isValid) {
                this.classList.add('is-invalid');
            }
        });
    });
}

// 生成字母序列用于site_holder (A, B, C, ...)
function getAlphabetSequence(length) {
    const result = [];
    let current = 65; // ASCII for 'A'
    
    for (let i = 0; i < length; i++) {
        result.push(String.fromCharCode(current + i));
    }
    
    return result;
}

// 生成子晶格配置
function generateSublattices(count) {
    const container = document.getElementById('sublattices-container');
    container.innerHTML = '';
    
    const siteHolders = getAlphabetSequence(count);
    
    for (let i = 0; i < count; i++) {
        const sublattice = document.createElement('div');
        sublattice.className = 'sublattice-item';
        sublattice.dataset.index = i;
        
        // 默认元素列表
        const defaultElements = "CO, CU, FE, NI, TA, TI, W";
        
        sublattice.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-2">
                <h6>
                    <span data-i18n="prep.sublattice_prefix">子晶格</span> ${siteHolders[i]}
                </h6>
                <span class="badge bg-primary">site_holder: ${siteHolders[i]}</span>
            </div>
            <div class="row">
                <div class="col-md-6">
                    <div class="mb-2">
                        <label class="form-label" data-i18n="prep.site2sub_label">Wyckoff与sublattice的对应关系</label>
                        <input type="text" class="form-control site2sub" value="[${i}]" readonly>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="mb-2">
                        <label class="form-label" data-i18n="prep.occup_atoms_label">在tdb中想要写成的占位分数(只与最终生成的tdb文件有关)</label>
                        <input type="number" class="form-control occup-atoms" value="1" min="1">
                    </div>
                </div>
            </div>
            <div class="mb-2">
                <label class="form-label" data-i18n="prep.allowed_elements_label">允许的元素 (comp)</label>
                <input type="text" class="form-control allowed-elements" value="${defaultElements}">
            </div>
        `;
        
        container.appendChild(sublattice);
    }
}

function getI18nText(path, fallback) {
    try {
        const keys = path.split('.');
        const lang = localStorage.getItem('preferredLang') || 'en';
        // 访问全局 window.i18nData
        let res = window.i18nData ? window.i18nData[lang] : null;
        if (!res) return fallback;
        for (const key of keys) {
            res = res[key];
        }
        return res || fallback;
    } catch (e) {
        return fallback;
    }
}

// 上传文件到服务器
async function uploadFileToServer(file) {
    try {
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch('/upload_file', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (!response.ok || !result.success) {
            // 获取翻译：优先找 prep.upload_fail，找不到用 '文件上传失败'
            const failMsg = getI18nText('prep.upload_fail', 'upload failed');
            throw new Error(result.message || failMsg);
        }
        
        return result;
    } catch (error) {
        console.error('Upload error:', error);
        
        // 获取翻译：优先找 prep.upload_fail_prefix，找不到用 '文件上传失败: '
        const errorPrefix = getI18nText('prep.upload_fail_prefix', 'upload failed: ');
        
        showAlert(`${errorPrefix}${error.message}`, 'danger');
        throw error;
    }
}

function safeApplyTranslation() {
    try {
        // 检查全局翻译函数是否存在
        if (typeof window.updatePageContent === 'function') {
            // 从本地存储读取当前语言偏好
            const currentLang = localStorage.getItem('preferredLang') || 'en';
            // 触发翻译扫描
            window.updatePageContent(currentLang);
        }
    } catch (e) {
        console.error("i18n refresh failed:", e);
    }
}

// 添加描述符文件
function addDescriptorItem(filePath = '', indexName = 'symbol', columns = []) {
    const container = document.getElementById('descriptors-container');
    const itemCount = container.children.length;
    const itemId = `descriptor-${itemCount}`;
    
    // 创建描述符项
    const descriptorItem = document.createElement('div');
    descriptorItem.className = 'descriptor-item';
    descriptorItem.id = itemId;
    
    // 初始列名HTML（使用示例列名）
    let columnsHtml = generateColumnsHtml(sampleColumns, indexName, columns);
    
    descriptorItem.innerHTML = `
        <button type="button" class="remove-item" data-id="${itemId}">
            <i class="fas fa-times"></i>
        </button>
        <h6>
            <span data-i18n="prep.descriptor_file_prefix">Descriptor Settings</span> #${itemCount + 1}
        </h6>
        <div class="mb-3">
            <label class="form-label" data-i18n="prep.file_path_label">File Path</label>
            <div class="input-group">
                <input type="text" class="form-control descriptor-file" value="${filePath}">
                <button class="btn btn-outline-primary select-file" type="button" data-target="${itemId}">
                    <i class="fas fa-folder-open"></i>
                </button>
            </div>
        </div>
        <div class="row">
            <div class="col-md-6">
                <div class="mb-2">
                    <label class="form-label" data-i18n="prep.index_name_label">Index col name(index_name)</label>
                    <input type="text" class="form-control descriptor-index" value="${indexName}">
                    <div class="form-text" data-i18n="prep.index_hint">Please choose one of the column names as index</div>
                </div>
            </div>
        </div>
        <div class="mb-2">
            <label class="form-label" data-i18n="prep.select_cols_label">describe col name (col_name)</label>
            <div class="column-selector">
                ${columnsHtml}
            </div>
        </div>
    `;
    
    container.appendChild(descriptorItem);

    safeApplyTranslation();

    // 添加删除按钮事件
    descriptorItem.querySelector('.remove-item').addEventListener('click', function() {
        document.getElementById(this.dataset.id).remove();
        renumberDescriptors();
    });
    
    // 添加文件选择按钮事件
    descriptorItem.querySelector('.select-file').addEventListener('click', async function() {
        const button = this;
        const originalIcon = button.innerHTML;
        const targetId = this.dataset.target;
        const descriptorItem = document.getElementById(targetId);
        const filePathInput = descriptorItem.querySelector('.descriptor-file');
        const indexInput = descriptorItem.querySelector('.descriptor-index');
        
        // 创建一个隐藏的文件选择输入
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = '.csv'; // 只接受CSV文件
        
        // 当用户选择文件后
        fileInput.addEventListener('change', async function(e) {
            if (e.target.files.length > 0) {
                try {
                    // 显示上传中状态
                    button.disabled = true;
                    button.innerHTML = '<span class="uploading-spinner"></span> uploading...';
                    
                    const file = e.target.files[0];
                    showAlert(`uploading: ${file.name}`, 'info');
                    
                    // 上传文件到服务器
                    const uploadResult = await uploadFileToServer(file);
                    
                    // 更新文件路径为服务器上的路径
                    filePathInput.value = uploadResult.relative_path;
                    
                    // 读取文件内容以获取列名
                    const response = await fetch(`/${uploadResult.relative_path}`);
                    const content = await response.text();
                    
                    // 解析CSV内容获取列名（使用更健壮的解析方法）
                    const columns = parseCsvHeaders(content);
                    
                    if (columns.length > 0) {
                        // 更新列选择器
                        updateColumnSelector(descriptorItem, columns);
                        
                        // 如果索引名称不在列名中，自动选择第一列作为索引
                        if (!columns.includes(indexInput.value)) {
                            indexInput.value = columns[0];
                        }
                        
                        showAlert(`upload success: find ${columns.length} cols`, 'success');
                        console.log('please check cols:', columns);
                    } else {
                        showAlert('cannot find cols in this file', 'warning');
                    }
                    
                } catch (error) {
                    console.error('load file fails:', error);
                    showAlert(`load file fails: ${error.message}`, 'danger');
                } finally {
                    // 恢复按钮状态
                    button.disabled = false;
                    button.innerHTML = originalIcon;
                }
            }
        });
        
        // 触发文件选择对话框
        fileInput.click();
    });
    

    try {
        if (typeof window.updatePageContent === 'function') {
            const currentLang = localStorage.getItem('preferredLang') || 'en';
            window.updatePageContent(currentLang);
        }
    } catch (e) {
        console.warn("翻译更新失败，但不影响功能操作:", e);
    }
}

    // 生成列选择器HTML
    function generateColumnsHtml(columns, indexName, selectedColumns) {
        let html = '';
        columns.forEach(column => {
            // 确定是否选中
            const isSelected = selectedColumns.includes(column) || 
                            column === indexName ||
                            (selectedColumns.length === 0 && ['symbol', 'atomic_number'].includes(column));
            
            html += `
                <div class="form-check">
                    <input class="form-check-input column-checkbox" type="checkbox" value="${column}" 
                        id="${generateId(column)}" ${isSelected ? 'checked' : ''}>
                    <label class="form-check-label" for="${generateId(column)}">
                        ${column}
                    </label>
                </div>
            `;
        });
        return html;
    }

    // 更新列选择器
    function updateColumnSelector(descriptorItem, columns) {
        const columnSelector = descriptorItem.querySelector('.column-selector');
        if (!columnSelector) return;
        
        // 获取当前索引名称
        const indexName = descriptorItem.querySelector('.descriptor-index').value;
        
        // 获取当前已选中的列
        const currentlySelected = Array.from(descriptorItem.querySelectorAll('.column-checkbox:checked'))
            .map(checkbox => checkbox.value);
        
        // 生成新的列HTML
        columnSelector.innerHTML = generateColumnsHtml(columns, indexName, currentlySelected);
    }

    // 解析CSV文件头（更健壮的实现）
    function parseCsvHeaders(csvContent) {
        // 处理空内容
        if (!csvContent.trim()) return [];
        
        // 分割成行（处理可能的不同换行符）
        const lines = csvContent.split(/\r\n|\n|\r/).filter(line => line.trim() !== '');
        
        // 取第一行作为表头
        const headerLine = lines[0].trim();
        
        // 简单CSV解析器，处理带引号的字段
        const headers = [];
        let currentField = '';
        let inQuotes = false;
        let quoteChar = '"';
        
        for (let i = 0; i < headerLine.length; i++) {
            const char = headerLine[i];
            
            // 处理引号
            if (char === '"' || char === "'") {
                // 如果是相同的引号且是结尾
                if (inQuotes && char === quoteChar) {
                    // 检查下一个字符是否是另一个引号（转义）
                    if (headerLine[i + 1] === char) {
                        currentField += char;
                        i++; // 跳过下一个引号
                    } else {
                        inQuotes = false;
                    }
                } else if (!inQuotes) {
                    inQuotes = true;
                    quoteChar = char;
                } else {
                    // 不同类型的引号，作为普通字符处理
                    currentField += char;
                }
            } 
            // 处理逗号分隔符（不在引号中时）
            else if (char === ',' && !inQuotes) {
                headers.push(currentField.trim());
                currentField = '';
            } 
            // 普通字符
            else {
                currentField += char;
            }
        }
        
        // 添加最后一个字段
        if (currentField.trim() !== '') {
            headers.push(currentField.trim());
        }
        
        return headers;
    }

    // 生成唯一ID
    function generateId(str) {
        return str.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
    }

    // 示例列名 - 作为 fallback
    const sampleColumns = [
        'symbol', 'atomic_number', 'atomic_weight', 'periodic', 
        'family', 'Calculated_radius_pm', 'Electronegativity_Allen',
        'melting_point', 'boiling_point', 'density'
    ];

    // 更新列选择器函数
    function updateColumnSelector(descriptorItem, columns) {
        const columnSelector = descriptorItem.querySelector('.column-selector');
        if (!columnSelector) return;
        
        // 清空现有列
        columnSelector.innerHTML = '';
        
        // 获取当前索引名称
        const indexName = descriptorItem.querySelector('.descriptor-index').value;
        
        // 添加新列
        columns.forEach(column => {
            // 检查列名是否有效
            if (!column) return;
            
            // 默认选中索引列和几个常用列
            const isSelected = column === indexName || 
                            ['atomic_number', 'atomic_weight', 'symbol'].includes(column);
            
            const columnHtml = `
                <div class="form-check">
                    <input class="form-check-input column-checkbox" type="checkbox" value="${column}" 
                        id="${descriptorItem.id}-col-${column}" ${isSelected ? 'checked' : ''}>
                    <label class="form-check-label" for="${descriptorItem.id}-col-${column}">
                        ${column}
                    </label>
                </div>
            `;
            
            columnSelector.innerHTML += columnHtml;
        });
    }

// 重新编号描述符
function renumberDescriptors() {
    const items = document.querySelectorAll('.descriptor-item');
    items.forEach((item, index) => {
        item.querySelector('h6').textContent = `描述符文件 #${index + 1}`;
    });
}

// 显示通知提示
function showAlert(message, type = 'info') {
    const alertContainer = document.querySelector('.alert-container');
    if (!alertContainer) {
        console.warn('Alert container not found! Message:', message);
        return;
    }
    
    const alert = document.createElement('div');
    alert.className = `alert alert-${type} alert-dismissible fade show`;
    alert.role = 'alert';
    alert.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    
    alertContainer.appendChild(alert);
    
    // 3秒后自动关闭
    setTimeout(() => {
        const bsAlert = new bootstrap.Alert(alert);
        bsAlert.close();
    }, 3000);
}

// 验证所有路径输入
function validateAllPaths() {
    const pathInputs = document.querySelectorAll('.path-input');
    let allValid = true;
    
    pathInputs.forEach(input => {
        const isFilePath = input.id.includes('file');
        const isValid = validatePath(input.value, isFilePath);
        
        if (!isValid) {
            input.classList.add('is-invalid');
            allValid = false;
        } else {
            input.classList.remove('is-invalid');
            input.classList.add('is-valid');
        }
    });
    
    return allValid;
}

// 收集表单数据并转换为JSON
function collectFormData() {
    // 先验证所有路径
    if (!validateAllPaths()) {
        showAlert('请修正路径输入中的错误', 'warning');
        return null;
    }
    
    // 基本设置
    const basicData = {
        phase_name: document.getElementById('phase-name').value,
        record_path: document.getElementById('record-path').value,
        structure_file: document.getElementById('structure-file').value,
        structure_out_file: document.getElementById('structure-out-file').value,
        structure_convert_to_primitive: document.getElementById('convert-to-primitive').value,
        cif_sublatt: document.getElementById('cif-sublatt').value,
        init_random_n: parseInt(document.getElementById('init-random-n').value)
    };
    
    // TDB模型设置
    const sublatticeCount = parseInt(document.getElementById('sublattice-number').value);
    const sublattices = document.querySelectorAll('.sublattice-item');
    
    const siteHolder = [];
    const site2sub = [];
    const occupAtomsInTdb = [];
    const comp = [];
    
    sublattices.forEach(sublattice => {
        const index = parseInt(sublattice.dataset.index);
        siteHolder.push(getAlphabetSequence(sublatticeCount)[index]);
        site2sub.push(JSON.parse(sublattice.querySelector('.site2sub').value));
        occupAtomsInTdb.push(parseInt(sublattice.querySelector('.occup-atoms').value));
        comp.push(sublattice.querySelector('.allowed-elements').value.split(', '));
    });
    
    const tdbModel = {
        site_holder: siteHolder,
        site2sub: site2sub,
        sublattice_number: sublatticeCount,
        occup_atoms_in_tdb: occupAtomsInTdb,
        comp: comp,
        Atom_ref: {
            file: document.getElementById('atom-ref-file').value,
            index_name: document.getElementById('atom-ref-index').value,
            col_name: document.getElementById('atom-ref-col').value
        }
    };
    
    // AL循环设置
    const questParams = {};
    document.querySelectorAll('.quest-param').forEach(param => {
        questParams[param.dataset.param] = parseInt(param.value);
    });

    // 获取选中的模型和超参数
    const mlModel = document.getElementById('ml-model').value;
    const mlHyperParameters = document.getElementById('ml-hyper-parameters-json').value;
    
    // 描述符设置 - 强制col_name以列表格式存储
    const descriptors = {};
    document.querySelectorAll('.descriptor-item').forEach(item => {
        const filePath = item.querySelector('.descriptor-file').value;
        const indexName = item.querySelector('.descriptor-index').value;
        
        const selectedColumns = [];
        item.querySelectorAll('.column-checkbox:checked').forEach(checkbox => {
            selectedColumns.push(checkbox.value);
        });
        
        if (filePath) {
            descriptors[filePath] = {
                index_name: indexName,
                // 强制以数组形式存储，即使只有一个元素
                col_name: [...selectedColumns]
            };
        }
    });
    
    const alSet = {
        ML_model: document.getElementById('ml-model').value,
        ML_style: document.getElementById('ml-style').value,
        descriptor: descriptors,
        ML_hyper_parameters: mlHyperParameters,
        normalizer: document.getElementById('normalizer').value,
        _c: "normalizer has two ways to choose: Zscore or mmscale",
        eigen_weight: document.getElementById('eigen-weight').value.split(', ').map(Number),
        iter_path: [],
        quest: questParams,
        generate_DFT_path: document.getElementById('generate-dft-path').value,
        calced_DFT_path: document.getElementById('calced-dft-path').value,
        pkl_phase_path: document.getElementById('pkl-phase-path').value,
        pkl_show_control: document.getElementById('pkl-show-control').value
    };
    
    // 组合所有数据
    return {
        ...basicData,
        tdb_model: tdbModel,
        AL_set: alSet
    };
}

// 保存到服务器
function saveToServer() {
    const data = collectFormData();
    if (!data) return; // 如果数据无效，不发送

    let filename = document.getElementById('custom-filename').value.trim();
    if (!filename) filename = 'input';
    if (!filename.endsWith('.json')) {
        filename += '.json';
    }
    // 禁用按钮防止重复提交
    const saveBtn = document.getElementById('save-json-btn');
    const originalHtml = saveBtn.innerHTML;
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> saving...';

    // 获取当前语言，用于 fallback
    const currentLang = localStorage.getItem('preferredLang') || 'zh';
    
    fetch('/save_input_json', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
                filename: filename,  // 发送文件名
                data: data     // 发送数据内容
            })
    })
    .then(response => {
        // 即使 response.ok 为 false (如 400, 500)，我们也尝试解析 JSON 获取 message_key
        return response.json().then(json => {
            if (!response.ok) return Promise.reject(json);
            return json;
        });
    })
    .then(result => {
        if (result.success) {
            // 动态翻译后端返回的 key，如果找不到则显示默认文本
            const msg = getI18nText(result.message_key, '配置已成功保存');
            const filePathMsg = result.file_path ? `: ${result.file_path}` : '';
            showAlert(msg + filePathMsg, 'success');
        } else {
            const errorMsg = getI18nText(result.message_key, result.message || '保存失败');
            showAlert(errorMsg, 'danger');
        }
    })
    .catch(error => {
        console.error('保存出错:', error);
        // 翻译通用的网络错误 key
        const netError = getI18nText('api.err_network', '保存失败，请检查网络连接或重试');
        showAlert(netError, 'danger');
    })
    .finally(() => {
        // 核心：无论如何都会执行到这里，恢复按钮
        saveBtn.disabled = false;
        saveBtn.innerHTML = originalHtml;
        console.log("Button restored."); 
    });
}

// 预览JSON
function previewJson() {
    const data = collectFormData();
    if (!data) return; // 如果数据无效，不预览
    
    const jsonString = JSON.stringify(data, null, 2);
    document.getElementById('json-output').textContent = jsonString;
    document.getElementById('json-preview').classList.remove('d-none');
}

// 文件选择按钮通用处理函数
async function handleFileSelect(button) {
    const targetId = button.dataset.target;
    const filePathInput = document.getElementById(targetId);
    const originalIcon = button.innerHTML;
    
    // 创建文件选择输入
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    
    // 根据目标ID设置文件类型过滤
    if (targetId.includes('structure-file') || targetId.includes('structure-out-file')) {
        fileInput.accept = '.cif,.poscar,POSCAR'; // 结构文件
    } else if (targetId.includes('atom-ref-file')) {
        fileInput.accept = '.csv'; // 参考文件
    }
    
    // 当用户选择文件后
    fileInput.addEventListener('change', async function(e) {
        if (e.target.files.length > 0) {
            try {
                // const uploadingText = getI18nText('prep.uploading', '上传中...');
                const uploadStartText = getI18nText('prep.upload_start', 'Uploading: ');
                const uploadSuccessText = getI18nText('prep.upload_success', 'Upload success');
                // const parseErrorText = getI18nText('prep.parse_error', '未能从CSV文件中解析出列名');
                // const uploadFailPrefix = getI18nText('prep.upload_fail_prefix', '文件处理失败: ');
                // 显示上传中状态
                button.disabled = true;
                button.innerHTML = '<span class="uploading-spinner"></span> ${uploadingText}';
                
                const file = e.target.files[0];
                showAlert(`${uploadStartText}${file.name}`, 'info');
                
                // 上传文件到服务器
                const uploadResult = await uploadFileToServer(file);
                
                // 更新文件路径为服务器上的路径
                filePathInput.value = uploadResult.relative_path;
                
                // 如果是路径输入，触发验证
                if (filePathInput.classList.contains('path-input')) {
                    filePathInput.dispatchEvent(new Event('input'));
                }
                
                showAlert(`${uploadSuccessText}: ${uploadResult.file_path}`, 'success');
            } catch (error) {
                console.error('${uploadFailPrefix}:', error);
            } finally {
                // 恢复按钮状态
                button.disabled = false;
                button.innerHTML = originalIcon;
            }
        }
    });
    
    // 触发文件选择对话框
    fileInput.click();
}

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', function() {
    // 设置路径验证
    setupPathValidation();
    
    // 初始化子晶格
    const initialSublatticeCount = parseInt(document.getElementById('sublattice-number').value);
    generateSublattices(initialSublatticeCount);
    
    // 初始化描述符
    addDescriptorItem('eigenvalue/periodic_table.csv', 'symbol', [
        'atomic_number', 'atomic_weight', 'periodic', 'family', 
        'Calculated_radius_pm', 'Electronegativity_Allen'
    ]);
    addDescriptorItem('eigenvalue/base_energy.csv', 'symbol', ['E_atom_eV_2']);
    
    // 更新子晶格按钮事件
    document.getElementById('update-sublattices').addEventListener('click', function() {
        const count = parseInt(document.getElementById('sublattice-number').value);
        if (count > 0) {
            generateSublattices(count);
            // 更新特征权重输入框的提示
            document.querySelector('#eigen-weight + .form-text').textContent = 
                `以逗号分隔的权重值，与子晶格数量(${count})对应`;
        }
    });
    
    // 添加描述符按钮事件
    document.getElementById('add-descriptor').addEventListener('click', function() {
        addDescriptorItem();
    });
    
    // 保存到服务器按钮事件
    document.getElementById('save-json-btn').addEventListener('click', saveToServer);
    
    // 预览JSON按钮事件
    document.getElementById('preview-json-btn').addEventListener('click', previewJson);
    
    // 取消按钮事件
    document.getElementById('cancel-btn').addEventListener('click', function() {
        if (confirm('确定要取消并放弃所有更改吗？')) {
            document.getElementById('json-preview').classList.add('d-none');
        }
    });
    
    // 为所有文件选择按钮添加事件
    document.querySelectorAll('.file-select-btn').forEach(button => {
        button.addEventListener('click', function() {
            handleFileSelect(this);
        });
    });

        document.getElementById('ml-model').addEventListener('change', function() {
            generateHyperParameters(this.value);
        });

        document.addEventListener('DOMContentLoaded', function() {
            const initialModel = document.getElementById('ml-model').value;
            generateHyperParameters(initialModel);
        });
});