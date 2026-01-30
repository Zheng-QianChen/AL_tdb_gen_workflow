// Console functionality implementation
const btnStart = document.getElementById('btnStart');
const btnPause = document.getElementById('btnPause');
const btnStop = document.getElementById('btnStop');
const btnRefresh = document.getElementById('btnRefresh');
const btnReloadInput = document.getElementById('btnReloadInput');
const statusDiv = document.getElementById('status');
const logDiv = document.getElementById('log');

let activeConfigName = 'input.json'; // Default monitored filename
let ws;
let reconnectInterval;
let statusCheckInterval;
let startTime = null;
let runtimeInterval = null;
let recordPath = null; // Store record_path obtained from input.json (filesystem path)
let fetchTimeout = null; // For timeout control

btnStart.onclick = doStart;

// --- Core Logic: UI Update Function ---
// This function is the endpoint of all data flows, implementing data-driven interface
function updateUIWithConfig(data) {
    if (!data) return;

    // 1. Define mapping relationships
    const statusMappings = [
        { id: 'phase-name', path: 'phase_name', defaultValue: 'Not Set' },
        { id: 'ml-model', path: 'AL_set.ML_model', defaultValue: 'Not Set' }
    ];

    // 2. Update basic text information
    statusMappings.forEach(item => {
        const value = item.path.split('.').reduce((obj, key) => {
            return obj && obj[key] !== undefined ? obj[key] : undefined;
        }, data);
        
        const element = document.getElementById(item.id);
        if (element) {
            element.textContent = value !== undefined ? value : item.defaultValue;
        }
    });

    // 3. Handle record file path linkage
    if (data.record_path) {
        // Update global recordPath for use by readRecordFile
        recordPath = '/get_data_file/'+data.record_path + '/record.txt';
        readRecordFile(); 
    } else {
        recordPath = null;
        document.getElementById('current-iteration').textContent = 'No Path';
        document.getElementById('current-operation-number').textContent = 'No Path';
    }
}

// --- API Call: Get System Status ---
async function fetchSystemStatus(filename = activeConfigName) {
    // Only show "Loading" during manual refresh or initial load
    // resetLoadingState(); 

    if (fetchTimeout) clearTimeout(fetchTimeout);
    const abortController = new AbortController();
    fetchTimeout = setTimeout(() => abortController.abort(), 10000);

    try {
        // [Improvement]: Specify filename through query parameter, support concurrent monitoring of different configs
        const response = await fetch(`/get_config_status?filename=${encodeURIComponent(filename)}`, { 
            signal: abortController.signal 
        });

        if (!response.ok) throw new Error(`HTTP error: ${response.status}`);
        
        const data = await response.json();
        updateUIWithConfig(data);
        
    } catch (error) {
        console.error('Failed to fetch system status:', error);
        // If failed, update UI feedback
        const phaseEl = document.getElementById('phase-name');
        if (phaseEl) phaseEl.textContent = error.name === 'AbortError' ? 'Timeout' : 'Connection Failed';
    }
}

// Function to change input.json configuration file
async function loadSpecificConfig() {
    const filenameInput = document.getElementById('target-config-file');
    const filename = filenameInput.value.trim();
    if (!filename) {
        alert("Please enter filename");
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
            // On success, refresh system status display (e.g., ML model name, current phase name, etc.)
            activeConfigName = filename; // Update currently monitored filename
            // If backend directly returns new config content, update UI directly
            const data = await response.json();
            activeConfigName = filename;
            if (data) {
                updateUIWithConfig(data);
                initWebSocket(filename);
                const newUrl = `${window.location.pathname}?task=${encodeURIComponent(filename)}`;
                window.history.pushState({ path: newUrl }, '', newUrl);
                addToLog(`Monitoring task switched to: ${filename}`, 'info');
            } else {
                alert("Loading failed: File does not exist or backend route not defined");
            }
            // Can print a log line in console
            addToLog(`System successfully switched configuration file to: ${filename}`, 'info');
            if (typeof showAlert === 'function') {
                showAlert(getI18nText('api.load_success', 'Configuration loaded successfully'), 'success');
            }
        } else {
            alert("Loading failed: " + (result.detail || "File does not exist"));
        }
    } catch (error) {
        console.error("Error loading configuration:", error);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}


// Initialize WebSocket connection
function initWebSocket(filename = activeConfigName) {
    if (ws) ws.close(); // Close old connection first
    if (reconnectInterval) clearInterval(reconnectInterval);
    
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUri = `${wsProtocol}//${window.location.host}/ws?task=${encodeURIComponent(filename)}`;
    
    addToLog(`Attempting to connect to WebSocket: ${wsUri}`, 'websocket');
    
    ws = new WebSocket(wsUri);
    
    ws.onopen = function() {
        addToLog('WebSocket connection established', 'websocket');
        statusDiv.textContent = 'Connected';
        statusDiv.style.backgroundColor = '#e8f5e9';
        statusDiv.style.color = '#198754';
    };
    
    ws.onclose = function(event) {
        addToLog(`WebSocket connection closed (code: ${event.code}), reconnecting...`, 'websocket');
        statusDiv.textContent = 'Connection closed, reconnecting...';
        statusDiv.style.backgroundColor = '#fff3cd';
        statusDiv.style.color = '#fd7e14';
        
        // Exponential backoff reconnection strategy
        let delay = 1000;
        reconnectInterval = setInterval(() => {
            if (ws.readyState === WebSocket.CLOSED) {
                addToLog(`Attempting to reconnect (delay: ${delay}ms)`, 'websocket');
                initWebSocket();
                delay = Math.min(delay * 2, 10000);
            } else {
                clearInterval(reconnectInterval);
            }
        }, delay);
    };
    
    ws.onerror = function(error) {
        addToLog(`WebSocket error: ${error}`, 'error');
        statusDiv.textContent = `Connection error`;
        statusDiv.style.backgroundColor = '#f8d7da';
        statusDiv.style.color = '#dc3545';
    };
    
    // Handle received messages
    ws.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            addToLog(data.content || data.message, data.type);
            
            // Parse system status data in message and update
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

// Add log to page
function addToLog(message, type = 'info') {
    try {
        const now = new Date();
        const timestamp = now.toLocaleTimeString('en-US', {
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
        console.error('Failed to add log:', e);
    }
}

// Update status display
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
                btnPause.innerHTML = '<i class="fas fa-play"></i> Resume';
                // Stop runtime timer when paused
                if (runtimeInterval) {
                    clearInterval(runtimeInterval);
                    runtimeInterval = null;
                }
            } else {
                statusIndicator.classList.add('status-running');
                btnPause.innerHTML = '<i class="fas fa-pause"></i> Pause';
                // Start or resume runtime timer
                if (!runtimeInterval) {
                    if (!startTime) startTime = new Date();
                    updateRuntime();
                    runtimeInterval = setInterval(updateRuntime, 1000);
                }
            }
        } else {
            statusIndicator.classList.add('status-stopped');
            // Reset runtime when stopped
            if (runtimeInterval) {
                clearInterval(runtimeInterval);
                runtimeInterval = null;
            }
            startTime = null;
            if (runtime) runtime.textContent = '00:00:00';
        }
    }
}

// Update runtime display
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

// Status update handling
async function StatusUpdates() {
    if (statusCheckInterval) clearInterval(statusCheckInterval);
    try {
        const userId = "guest";
        const config = activeConfigName.replace('.json', '');
        const url = `/status?user_id=${encodeURIComponent(userId)}&configname=${encodeURIComponent(config)}`;
        const response = await fetch(url, {
            method: 'GET', // Match backend GET
            headers: { 'Accept': 'application/json' }
            // Never write body here
        });
        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }
        const data = await response.json();
        
        // Update main status indicator
        updateStatusDisplay(data.running, data.paused, data.status_text);
        
        // Update console status
        statusDiv.textContent = data.status_text;
        
        // Update button states
        btnStart.disabled = data.running;
        btnPause.disabled = !data.running;
        btnStop.disabled = !data.running;
        
        // Update console status styles
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
        addToLog(`Failed to get status: ${e}`, 'error');
        console.error('Failed to get status:', e);
    }
}

// Start button click event
async function doStart() {
    // addToLog(`in doStart`, 'info');
    try {
        const configRes = await fetch(`/get_config_status?filename=${encodeURIComponent(activeConfigName)}`);
        const configData = await configRes.json();
        addToLog(`Requesting to start task: ${activeConfigName}...`, 'status-update');
        const response = await fetch(`/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: "guest",
                configname: activeConfigName.replace('.json', ''),
                // config: configData  // Send complete configuration
            })
        });
        const result = await response.json();
        if (response.ok && result.status === "success") {
            addToLog("Task started successfully", 'info');
        } else {
            throw new Error(result.message || "Start failed");
        }
    } catch (e) {
        addToLog(`Start request failed: ${e}`, 'error');
    }
    StatusUpdates();
}

// Pause/Resume button click event
async function togglePause() {
    try {
        addToLog('Sending pause/resume request...', 'status-update');
        const response = await fetch('/pause', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: "guest",
                configname: activeConfigName.replace('.json', ''),})
        });
        if (!response.ok) {
            throw new Error(`Pause/resume request failed: ${response.status}`);
        }
        addToLog('Pause/resume request sent', 'status-update');
    } catch (e) {
        addToLog(`Pause/resume request failed: ${e}`, 'error');
    }
    StatusUpdates();
}

// Stop button click event
async function doStop() {
    try {
        addToLog('Sending stop request...', 'status-update');
        const response = await fetch('/stop' ,{
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: "guest",
                configname: activeConfigName.replace('.json', ''),})
        });
        if (!response.ok) {
            throw new Error(`Stop request failed: ${response.status}`);
        }
        addToLog('Stop request sent', 'status-update');
    } catch (e) {
        addToLog(`Stop request failed: ${e}`, 'error');
    }
    StatusUpdates();
}

// // Reload input.json button click event
// async function reloadInputJson() {
//     try {
//         // Disable button and show loading state
//         btnReloadInput.disabled = true;
//         btnReloadInput.innerHTML = '<i class="fas fa-spinner fa-spin"></i> loading...';
        
//         addToLog('reloading config...', 'status-update');

//         const response = await fetch('/reset', { method: 'POST' });
//         if (!response.ok) {
//             throw new Error(`request error: ${response.status}`);
//         }
        
//         // Call existing system status fetch function, which will re-read input.json
//         fetchSystemStatus();
        
//         addToLog('config reload success', 'status-update');
//     } catch (e) {
//         addToLog(`config reload fail: ${e}`, 'error');
//     } finally {
//         // Restore button state
//         btnReloadInput.disabled = false;
//         btnReloadInput.innerHTML = '<i class="fas fa-file-import"></i>  <span data-i18n="index.btn_reload">Reload input.json</span>';
//     }
// }

// Get operation status text description
function getOperationText(operationCode) {
    const operationMap = {
        '0': 'generating DFT inputs',
        '1': 'waiting DFT results',
        '2': 'training ML model',
    };
    return operationMap[operationCode] || `unknown (${operationCode})`;
}

// Get operation status CSS class
function getOperationClass(operationCode) {
    return operationCode ? `operation-${operationCode}` : 'operation-unknown';
}

// Reset loading state
function resetLoadingState() {
    const loadingElements = [
        'phase-name', 
        'current-iteration', 
        'current-operation-number'
    ];
    
    loadingElements.forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.innerHTML = '<span class="loading-spinner"></span>Loading...';
        }
    });
    
    const operationText = document.getElementById('current-operation-text');
    if (operationText) {
        operationText.className = 'operation-status operation-unknown';
        operationText.textContent = 'unknown';
    }
    StatusUpdates();
}

// Read local record.txt file through backend interface
async function readRecordFile() {
    if (!recordPath) {
        addToLog('record_path not obtained, cannot read record file', 'warning');
        document.getElementById('current-iteration').textContent = 'Cannot Retrieve';
        document.getElementById('current-operation-number').textContent = 'Cannot Retrieve';
        return;
    }
    
    try {
        // Set timeout
        const abortController = new AbortController();
        const timeoutId = setTimeout(() => abortController.abort(), 10000); // 10 second timeout
        
        addToLog(`try to read local file: ${recordPath}`, 'info');
        
        // Send file path to backend, have backend read file content
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
                addToLog(`Record file does not exist: ${recordPath}`, 'warning');
                document.getElementById('current-iteration').textContent = 'File Not Found';
                document.getElementById('current-operation-number').textContent = 'File Not Found';
            } else {
                addToLog(`Failed to read record file: HTTP status code ${response.status}`, 'error');
                document.getElementById('current-iteration').textContent = 'Read Failed';
                document.getElementById('current-operation-number').textContent = 'Read Failed';
            }
            return;
        }
        
        const result = await response.json();
        
        if (!result.success) {
            addToLog(`Failed to read record file: ${result.error || 'Unknown error'}`, 'error');
            document.getElementById('current-iteration').textContent = 'Read Failed';
            document.getElementById('current-operation-number').textContent = 'Read Failed';
            return;
        }
        
        // Split into lines and filter empty lines
        const lines = result.content.split('\n')
            .map(line => line.trim())
            .filter(line => line.length > 0);
        
        if (lines.length === 0) {
            addToLog('Record file is empty', 'info');
            document.getElementById('current-iteration').textContent = 'No Data';
            document.getElementById('current-operation-number').textContent = 'No Data';
            return;
        }
        
        // Get last line
        const lastLine = lines[lines.length - 1];
        // Split into two numbers
        const [iteration, operation] = lastLine.split(/\s+/).map(num => num.trim());
        
        if (iteration && operation) {
            // Update UI display
            document.getElementById('current-iteration').textContent = iteration;
            document.getElementById('current-operation-number').textContent = operation;
            
            const operationTextEl = document.getElementById('current-operation-text');
            operationTextEl.textContent = getOperationText(operation);
            // Remove old operation class and add new one
            operationTextEl.className = '';
            operationTextEl.classList.add('operation-status', getOperationClass(operation));
            
            addToLog(`Updated iteration info: iteration ${iteration}, operation ${operation} (${getOperationText(operation)})`, 'status-update');
        } else {
            addToLog(`Last line of record file has incorrect format: "${lastLine}"`, 'error');
            document.getElementById('current-iteration').textContent = 'Format Error';
            document.getElementById('current-operation-number').textContent = 'Format Error';
        }
    } catch (error) {
        if (error.name === 'AbortError') {
            addToLog('Reading record file timed out', 'error');
        } else {
            addToLog(`Error occurred while reading record file: ${error.message}`, 'error');
        }
        console.error('Record file read error:', error);
        document.getElementById('current-iteration').textContent = 'Load Failed';
        document.getElementById('current-operation-number').textContent = 'Load Failed';
    }
}

// function openVisualization() {
//     // Get currently monitored config filename, e.g., "B.json"
//     const taskName = activeConfigName; 
//     // Open new window, URL carries task name
//     window.open(`visualization.html?task=${encodeURIComponent(taskName)}`, '_blank');
// }

// Cleanup on page close
window.onbeforeunload = function() {
    if (ws) {
        ws.close(1000, "Page closing");
    }
    if (reconnectInterval) clearInterval(reconnectInterval);
    if (statusCheckInterval) clearInterval(statusCheckInterval);
    if (runtimeInterval) clearInterval(runtimeInterval);
    if (fetchTimeout) clearTimeout(fetchTimeout);
};

// --- Lifecycle Control ---
let statusTimer = null;

function startGlobalMonitoring() {
    // Clear old timer
    if (statusTimer) clearInterval(statusTimer);

    // 1. Execute once immediately
    fetchSystemStatus(activeConfigName);
    initWebSocket(activeConfigName);

    // 2. Set up periodic polling
    statusTimer = setInterval(() => {
        fetchSystemStatus(activeConfigName);
        StatusUpdates();
    }, 5000);
}

window.onload = function() {
    // Automatically get task name from URL (e.g., index.html?task=A.json)
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