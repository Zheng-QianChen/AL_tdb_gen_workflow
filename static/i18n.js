
/**
 * 核心双语切换逻辑
 */

// 1. 定义全局变量，方便其他 JS 文件（如 data_preparation.js）获取翻译
window.allLangData = null; 

// 2. 提供一个全局工具函数：根据 key 获取当前语言的文字
window.getI18nText = function(path, fallback = '') {
    if (!window.allLangData) return fallback;
    
    const lang = localStorage.getItem('preferredLang') || 'en';
    const keys = path.split('.');
    let result = window.allLangData[lang];
    
    for (const key of keys) {
        if (result && result[key] !== undefined) {
            result = result[key];
        } else {
            return fallback; // 没找到路径则返回默认值
        }
    }
    return result;
};

async function initLanguage() {
    const langSelect = document.getElementById('langSelect');
    if (!langSelect) return;

    // 1. 获取当前语言偏好，默认中文
    let currentLang = localStorage.getItem('preferredLang') || 'zh';
    langSelect.value = currentLang;

    // 2. 加载语言包
    try {
        const response = await fetch('/static/languages.json');
        const langData = await response.json();
        window.allLangData = langData; // 必须将读取的数据赋值给全局变量

        // 3. 定义更新函数
        window.updatePageContent = function(lang) {
            document.querySelectorAll('[data-i18n]').forEach(element => {
                const path = element.getAttribute('data-i18n').split('.');
                let text = langData[lang];
                
                // 深入查找 JSON 路径 (例如 common -> brand)
                for (const key of path) {
                    if (text) text = text[key];
                }

                if (text) {
                    // 如果元素内包含图标 (i 标签)，我们只替换文字节点
                    const icon = element.querySelector('i');
                    if (icon) {
                        // 保留图标，清空其他，再追加文字
                        element.innerHTML = ''; 
                        element.appendChild(icon);
                        element.appendChild(document.createTextNode(' ' + text));
                    } else {
                        // 没有图标，直接改文本
                        element.textContent = text;
                    }
                }
            });
            localStorage.setItem('preferredLang', lang);
            // 修改 HTML 的 lang 属性（符合 SEO 和无障碍标准）
            document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
        };

        // 4. 初始化执行一次
        updatePageContent(currentLang);

        // 5. 绑定切换事件
        langSelect.addEventListener('change', (e) => {
            updatePageContent(e.target.value);
        });

    } catch (error) {
        console.error("加载语言文件失败:", error);
    }
}



// 确保 DOM 加载完后执行
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLanguage);
} else {
    initLanguage();
}