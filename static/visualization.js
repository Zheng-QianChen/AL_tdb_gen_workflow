// --- 1. Get the currently monitored filename ---
const urlParams = new URLSearchParams(window.location.search);
// Priority: get task or filename parameter from URL, default to input.json if not present
let activeConfigName = urlParams.get('task') || urlParams.get('filename') || 'input.json';

// --- 2. Dynamic base path variables ---
let recordPath = null; 
// Image path will now be dynamically generated based on recordPath/fig
let IMAGE_BASE_PATH = '';
let csvPath = null; // iter.csv path
// Define variables
let itermax = 0;  // Current iteration variable
let process = 0;  // Current operation variable
let phaseName = ""; // Phase name

// Image cache - use localStorage to store image data
const IMAGE_CACHE = "al_visualization_image_cache";

// Data cache
const DATA_CACHE = "al_visualization_data_cache";


// Data cache
let totalIterations = 0;
let currentIteration = 1;
let fetchTimeout = null;
let csvData = []; // Store parsed CSV data
let csvRawContent = ""; // Store raw CSV content for error diagnosis

// Prediction image iteration range
let predImageMinIter = 1;
let predImageMaxIter = 0;
let currentPredIter1 = 1;  // Second image: default iter0001
let currentPredIter2 = 1;  // Third image: default itermax

window.addToLog = function(msg, type) { console.log(`[${type}] ${msg}`); };

window.onload = function() {
    // Automatically get task name from URL (e.g., index.html?task=A.json)
    const urlParams = new URLSearchParams(window.location.search);
    const taskFromUrl = urlParams.get('task');
    if (taskFromUrl) {
        activeConfigName = taskFromUrl;
        const input = document.getElementById('target-config-file');
        if (input) input.value = taskFromUrl;
    }
    bindEvents();
    loadSpecificConfig();
    
};

function bindEvents() {
    console.log("Binding button events...");
    
    // 1. Initialize data fetch timer, etc.
    initDataFetch();
    
    // 2. Bind iteration control button events
    const iterBtns = [
        { id: 'first-iter', action: () => changeIteration(1) },
        { id: 'prev-iter',  action: () => changeIteration(currentIteration - 1) },
        { id: 'next-iter',  action: () => changeIteration(currentIteration + 1) },
        { id: 'last-iter',  action: () => changeIteration(itermax) }
    ];

    iterBtns.forEach(btn => {
        const el = document.getElementById(btn.id);
        if (el) el.onclick = btn.action;
    });
    
    // 3. Prediction image 1 navigation control (second image)
    const pred1Btns = [
        { id: 'first-pred-1', action: () => updatePredImage(1, predImageMinIter) },
        { id: 'prev-pred-1',  action: () => updatePredImage(1, currentPredIter1 - 1) },
        { id: 'next-pred-1',  action: () => updatePredImage(1, currentPredIter1 + 1) },
        { id: 'last-pred-1',  action: () => updatePredImage(1, itermax) }
    ];

    pred1Btns.forEach(btn => {
        const el = document.getElementById(btn.id);
        if (el) el.onclick = btn.action;
    });
    
    const iterPred1 = document.getElementById('iter-pred-1');
    if (iterPred1) {
        iterPred1.onchange = function() {
            const iter = parseInt(this.value);
            if (!isNaN(iter)) updatePredImage(1, iter);
        };
    }
    
    // 4. Prediction image 2 navigation control (third image)
    const pred2Btns = [
        { id: 'first-pred-2', action: () => updatePredImage(2, predImageMinIter) },
        { id: 'prev-pred-2',  action: () => updatePredImage(2, currentPredIter2 - 1) },
        { id: 'next-pred-2',  action: () => updatePredImage(2, currentPredIter2 + 1) },
        { id: 'last-pred-2',  action: () => updatePredImage(2, itermax) }
    ];

    pred2Btns.forEach(btn => {
        const el = document.getElementById(btn.id);
        if (el) el.onclick = btn.action;
    });
    
    const iterPred2 = document.getElementById('iter-pred-2');
    if (iterPred2) {
        iterPred2.onchange = function() {
            const iter = parseInt(this.value);
            if (!isNaN(iter)) updatePredImage(2, iter);
        };
    }
    
    // 5. Tab switching listener
    const tabElements = document.querySelectorAll('#vizTabs button[data-bs-toggle="tab"]');
    tabElements.forEach(tab => {
        tab.addEventListener('shown.bs.tab', function() {
            updateAllImages();
        });
    });
}

async function fetchSystemStatus() {
    try {
        // [KEY] Include specific filename when requesting backend
        const response = await fetch(`/get_config_status?filename=${encodeURIComponent(activeConfigName)}`);
        const data = await response.json();
        
        if (data.record_path) {
            // Dynamically construct image address: record_path + /fig/
            let base = data.record_path.endsWith('/') ? data.record_path : data.record_path + '/';
            window.IMAGE_BASE_PATH = '/get_data_file/'+data.record_path + '/fig/';
            
            // Update path text on page for debugging
            const pathDisplay = document.getElementById('logs-image-path');
            if (pathDisplay) pathDisplay.textContent = `Current Path: ${window.IMAGE_BASE_PATH}`;
        }
        
        // Update iteration data
        // itermax = data.itermax || 0;
        // process = data.process || 0;

        // Trigger UI and image updates
        updateUIWithConfig(data);

        await readRecordFile(); 
        await readCsvFile();
        
        updateAllImages(); 
        updateIterationDisplay();
        
    } catch (e) {
        console.error("Failed to sync task status:", e);
    }
}

// Initialization function
function initDataFetch() {
    // Reset loading state
    resetLoadingState();
    
    // Initialize cache
    initImageCache();
    initDataCache();
    
    // Bind error details display button event
    document.getElementById('show-error-details').addEventListener('click', function() {
        const detailsElement = document.getElementById('csv-error-details');
        if (detailsElement.style.display === 'none' || detailsElement.style.display === '') {
            detailsElement.style.display = 'block';
            this.textContent = 'Hide Details';
        } else {
            detailsElement.style.display = 'none';
            this.textContent = 'Show Details';
        }
    });
    
    // Bind force refresh button event
    document.getElementById('force-refresh-main').addEventListener('click', function() {
        // Clear cache record for this image
        const formattedIter = String(currentIteration).padStart(4, '0');
        const baseImageUrl = `${IMAGE_BASE_PATH}iter.png`;
        
        try {
            const cache = JSON.parse(localStorage.getItem(IMAGE_CACHE) || '{}');
            if (cache[baseImageUrl]) {
                delete cache[baseImageUrl];
                localStorage.setItem(IMAGE_CACHE, JSON.stringify(cache));
                console.log('Comprehensive metrics chart cache cleared');
            }
        } catch (e) {
            console.error('Failed to clear cache:', e);
        }
        
        // Display refreshing status
        this.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Refreshing...';
        this.disabled = true;
        
        // Reload image
        updateMainImage().then(() => {
            // Restore button status
            this.innerHTML = '<i class="fas fa-sync-alt"></i> Force Refresh Comprehensive Metrics Chart';
            this.disabled = false;
        }).catch(() => {
            // Restore button status even on failure
            this.innerHTML = '<i class="fas fa-sync-alt"></i> Force Refresh Comprehensive Metrics Chart';
            this.disabled = false;
        });
    });
    
    // Set timer to sync data periodically (every 3 seconds)
    setInterval(() => {
        fetchSystemStatus(activeConfigName);
    }, 3000);
}


// Function to change input.json configuration file
async function loadSpecificConfig() {
    const filenameInput = document.getElementById('target-config-file');
    const filename = filenameInput.value.trim();
    if (!filename) {
        console.error("Please enter filename");
        return;
    }
    const btn = event.currentTarget;
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Loading...';

    try {
        const response = await fetch(`/get_config_status?filename=${encodeURIComponent(filename)}`);
        if (response.ok) {
            // On success, refresh system status display (e.g., ML model name, current phase name, etc.)
            activeConfigName = filename; // Update currently monitored filename
            // If backend directly returns new configuration content, update UI directly
            const data = await response.json();
            recordPath = '/get_data_file/'+data.record_path + '/record.txt';
            csvPath = '/get_data_file/'+data.record_path + '/iter.csv';
            const url = new URL(window.location);
            url.searchParams.set('task', filename); // Use task parameter uniformly
            window.history.pushState({}, '', url);
        } else {
            console.error("Loading failed: " + (result.detail || "File does not exist"));
        }
    } catch (error) {
        console.error("Error loading configuration:", error);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
    fetchSystemStatus(activeConfigName);
}


// Initialize image cache
function initImageCache() {
    if (!localStorage.getItem(IMAGE_CACHE)) {
        localStorage.setItem(IMAGE_CACHE, JSON.stringify({}));
    }
}

// Initialize data cache
function initDataCache() {
    if (!localStorage.getItem(DATA_CACHE)) {
        localStorage.setItem(DATA_CACHE, JSON.stringify({}));
    }
}

// Get image from cache
function getImageFromCache(url) {
    try {
        const cache = JSON.parse(localStorage.getItem(IMAGE_CACHE) || '{}');
        return cache[url] || null;
    } catch (e) {
        console.error('Failed to get image cache:', e);
        return null;
    }
}

// Save image to cache
function saveImageToCache(url, dataUrl) {
    try {
        const cache = JSON.parse(localStorage.getItem(IMAGE_CACHE) || '{}');
        // Limit cache size, keep only the most recent 20 images
        const cacheEntries = Object.entries(cache);
        if (cacheEntries.length >= 20) {
            // Delete oldest cache
            const oldestKey = cacheEntries[0][0];
            delete cache[oldestKey];
        }
        cache[url] = {
            data: dataUrl,
            timestamp: new Date().getTime()
        };
        localStorage.setItem(IMAGE_CACHE, JSON.stringify(cache));
    } catch (e) {
        console.error('Failed to save image cache:', e);
    }
}

// Get data from cache
function getDataFromCache(path) {
    try {
        const cache = JSON.parse(localStorage.getItem(DATA_CACHE) || '{}');
        return cache[path] || null;
    } catch (e) {
        console.error('Failed to get data cache:', e);
        return null;
    }
}

// Save data to cache
function saveDataToCache(path, data) {
    try {
        const cache = JSON.parse(localStorage.getItem(DATA_CACHE) || '{}');
        cache[path] = {
            data: data,
            timestamp: new Date().getTime()
        };
        localStorage.setItem(DATA_CACHE, JSON.stringify(cache));
    } catch (e) {
        console.error('Failed to save data cache:', e);
    }
}

// Reset loading state
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
            element.innerHTML = '<span class="loading-spinner"></span>Loading...';
        }
    });
    
    const operationText = document.getElementById('current-operation-text');
    if (operationText) {
        operationText.className = 'operation-status','operation-unknown';
        operationText.textContent = 'Unknown';
    }
    
    // Hide error messages
    document.getElementById('data-error').style.display = 'none';
    document.getElementById('csv-error-details').style.display = 'none';
}

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
    // Return an array containing all class names to be added
    if (operationCode !== undefined && operationCode !== null) {
        return ['operation-status', `operation-${operationCode}`];
    }
    return ['operation-status', 'operation-unknown'];
}


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
        csvPath = '/get_data_file/'+data.record_path + '/iter.csv';
        IMAGE_BASE_PATH = '/get_data_file/'+data.record_path + '/fig/';
        phaseName = data.phase_name || '';
    } else {
        recordPath = null;
        document.getElementById('current-iteration').textContent = 'No Path';
        document.getElementById('current-operation-number').textContent = 'No Path';
    }
}

// Read record file to get iteration information
async function readRecordFile() {
    if (!recordPath) {
        console.error('record_path not obtained, cannot read record file', 'warning');
        document.getElementById('current-iteration').textContent = 'Cannot Retrieve';
        document.getElementById('current-operation-number').textContent = 'Cannot Retrieve';
        return;
    }
    
    try {
        // Set timeout
        const abortController = new AbortController();
        const timeoutId = setTimeout(() => abortController.abort(), 10000); // 10 second timeout
        
        console.info(`try to read local file: ${recordPath}`, 'info');
        
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
                console.error(`Record file does not exist: ${recordPath}`, 'warning');
                document.getElementById('current-iteration').textContent = 'File Not Found';
                document.getElementById('current-operation-number').textContent = 'File Not Found';
            } else {
                console.error(`Failed to read record file: HTTP status code ${response.status}`, 'error');
                document.getElementById('current-iteration').textContent = 'Read Failed';
                document.getElementById('current-operation-number').textContent = 'Read Failed';
            }
            return;
        }

        const result = await response.json();
        
        if (!result.success) {
            console.error(`Failed to read record file: ${result.error || 'Unknown error'}`, 'error');
            document.getElementById('current-iteration').textContent = 'Read Failed';
            document.getElementById('current-operation-number').textContent = 'Read Failed';
            return;
        }
        
        // Split into lines and filter empty lines
        const lines = result.content.split('\n')
            .map(line => line.trim())
            .filter(line => line.length > 0);
        
        if (lines.length === 0) {
            console.error('Record file is empty', 'info');
            document.getElementById('current-iteration').textContent = 'No Data';
            document.getElementById('current-operation-number').textContent = 'No Data';
            return;
        }
        
        // Get last line
        const lastLine = lines[lines.length - 1];
        // Split into two numbers
        const [iteration, operation] = lastLine.split(/\s+/).map(num => num.trim());
        
        if (iteration && operation) {
            // Update variables
            itermax = parseInt(iteration);
            process = operation;
            // Adjust itermax based on process
            if (process != 2) {
                itermax = Math.max(1, itermax - 1);
            }
            predImageMaxIter = itermax;
            totalIterations = itermax;

            // Adjust itermax based on process
            document.getElementById('current-iteration').textContent = iteration;
            document.getElementById('current-operation-number').textContent = operation;

            const operationTextEl = document.getElementById('current-operation-text');
            operationTextEl.textContent = getOperationText(operation);
            
            operationTextEl.className = 'operation-status';
            const opClass = getOperationClass(operation);
            if (opClass) {
                operationTextEl.classList.add(opClass); 
            }
            console.info(`Updated iteration info: iteration ${iteration}, operation ${operation} (${getOperationText(operation)})`, 'status-update');
        } else {
            console.error(`Last line of record file has incorrect format: "${lastLine}"`, 'error');
            document.getElementById('current-iteration').textContent = 'Format Error';
            document.getElementById('current-operation-number').textContent = 'Format Error';
        }
    } catch (error) {
        if (error.name === 'AbortError') {
            console.error('Reading record file timed out', 'error');
        } else {
            console.error(`Error occurred while reading record file: ${error.message}`, 'error');
        }
        console.error('Record file read error:', error);
        document.getElementById('current-iteration').textContent = 'Load Failed';
        document.getElementById('current-operation-number').textContent = 'Load Failed';
    }
}



// Modified readCsvFile function with enhanced error handling and debugging info
function readCsvFile() {
    if (!csvPath) {
        console.log('csvPath not obtained, cannot read CSV file');
        showDataError('iter.csv file path not found');
        return;
    }
    // Print debug info to confirm requested path
    console.log('Attempting to read CSV file:', csvPath);
    
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
            
            // Print HTTP response status
            console.log('CSV file request response status:', response.status);
            
            if (!response.ok) {
                throw new Error(`HTTP status code: ${response.status}`);
            }
            return response.json();
        })
        .then(result => {
            // Extract CSV string content
            const content = result.content;
            
            // Print raw content preview to help debugging
            console.log('CSV file content preview:', content.substring(0, 200) + (content.length > 200 ? '...' : ''));
            
            csvRawContent = content;
            csvData = parseCsvContent(content);
            saveDataToCache(csvPath, csvData);
            updateMetricsFromCsv();
            console.log(`Successfully parsed CSV data, ${csvData.length} records total`);
        })
        .catch(error => {
            clearTimeout(timeoutId);
            console.error('CSV file read error:', error);
            
            // More detailed error information
            let errorMsg, errorDetails;
            if (error.name === 'AbortError') {
                errorMsg = 'CSV file read timeout';
                errorDetails = `Timeout error: reading file ${csvPath} did not respond within 10 seconds`;
            } else {
                errorMsg = `CSV file read failed: ${error.message}`;
                errorDetails = `Error details: ${error.stack}\nFile path: ${csvPath}`;
            }
            
            showDataError(errorMsg, errorDetails);
        });
    } catch (error) {
        console.error('Error occurred while reading CSV file:', error);
        showDataError(`Error processing CSV: ${error.message}`, 
            `Error details: ${error.stack}\nFile path: ${csvPath}`);
    }
}


// Modified CSV parsing function with relaxed format requirements
function parseCsvContent(content) {
    const data = [];
    let errorDetails = [];
    
    if (!content.trim()) {
        errorDetails.push("CSV file content is empty");
        showDataError("CSV file content is empty", errorDetails.join("\n"));
        return data;
    }
    
    // Split lines and filter empty lines
    const lines = content.split('\n')
        .map((line, index) => ({ line: line.trim(), row: index + 1 }))
        .filter(item => item.line.length > 0);
    
    if (lines.length < 2) {
        errorDetails.push(`CSV file content insufficient, needs at least header row and one data row, actually only has ${lines.length} rows`);
        showDataError("CSV file format error", errorDetails.join("\n"));
        return data;
    }
    
    // Parse header row
    const headerLine = lines[0];
    const headers = headerLine.line.split(',').map(header => header.trim());
    
    // Print header row info for debugging
    console.log(`CSV header row: ${headers.length} columns -`, headers);
    
    // Relax column count check, only warn without blocking
    if (headers.length !== 7) {
        errorDetails.push(`Warning: Header row format does not match expectations, expected 7 columns, actually ${headers.length} columns`);
        errorDetails.push(`Header row content: "${headerLine.line}"`);
    }
    
    // Parse data rows
    for (let i = 1; i < lines.length; i++) {
        const lineItem = lines[i];
        const values = lineItem.line.split(',').map(value => value.trim());
        
        // Also relax column count check
        if (values.length !== 7) {
            errorDetails.push(`Warning: Row ${lineItem.row} column count does not match expectations: expected 7 columns, actually ${values.length} columns`);
            // Don't skip, try to parse available data
        }
        
        try {
            // More robust parsing logic, handle possible missing values
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
            
            // Allow some fields to be empty, but need at least some valid data
            const hasValidData = Object.values(record).some(v => v !== null && !isNaN(v));
            if (hasValidData) {
                data.push(record);
            } else {
                errorDetails.push(`Row ${lineItem.row} has no valid data: "${lineItem.line}"`);
            }
        } catch (error) {
            errorDetails.push(`Error parsing row ${lineItem.row}: ${error.message}`);
            errorDetails.push(`Row content: "${lineItem.line}"`);
        }
    }
    
    // Even if there are errors, use data if available
    if (data.length > 0) {
        if (errorDetails.length > 0) {
            showDataError(`CSV file parsing has ${errorDetails.length} warnings, but successfully parsed ${data.length} valid records`, 
                errorDetails.join("\n\n") + "\n\nWill continue with available data");
        }
        return data;
    } else {
        errorDetails.push("No valid data records parsed");
        showDataError("No valid CSV data found", errorDetails.join("\n"));
        return [];
    }
}

// Update metrics display from CSV
function updateMetricsFromCsv() {
    if (csvData.length === 0) {
        showDataError('No valid CSV data found', 
            `CSV file path: ${csvPath}\n` +
            `Raw content preview: ${csvRawContent.substring(0, 500)}${csvRawContent.length > 500 ? '...' : ''}`);
        return;
    }
    
    // Find data based on current iteration
    let csvRecord = null;
    
    // Find record matching current iteration
    if (currentIteration && !isNaN(currentIteration)) {
        // Iterations start from 1, array index starts from 0
        const index = Math.min(currentIteration - 1, csvData.length - 1);
        if (index >= 0) {
            csvRecord = csvData[index];
        }
    }
    
    // If not found, use last record
    if (!csvRecord && csvData.length > 0) {
        csvRecord = csvData[csvData.length - 1];
    }
    
    // Update display
    if (csvRecord) {
        document.getElementById('data-count').textContent = csvRecord.trainingDataAmount;
        document.getElementById('train-rmse').textContent = csvRecord.rmseTrain.toFixed(3);
        document.getElementById('test-rmse').textContent = csvRecord.rmseTest.toFixed(3);
        document.getElementById('cv-info').textContent = `${csvRecord.foldNumRMSE} fold: ${csvRecord.rmseScore.toFixed(3)}`;
        document.getElementById('r2-score').textContent = csvRecord.r2Score.toFixed(3);
        
        // Update prediction chart R² values
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
    
    // Hide error messages
    document.getElementById('data-error').style.display = 'none';
    document.getElementById('csv-error-details').style.display = 'none';
}

// Display data error message
function showDataError(message, details) {
    const errorElement = document.getElementById('data-error');
    const detailsElement = document.getElementById('csv-error-details');
    
    errorElement.innerHTML = `Data Error: ${message} <button class="btn btn-sm btn-danger show-details-btn" id="show-error-details">Show Details</button>`;
    errorElement.style.display = 'block';
    
    // Format detailed information
    if (details) {
        // Replace newlines with HTML breaks
        let formattedDetails = details.replace(/\n/g, '<br>');
        // Display file path
        if (csvPath) {
            formattedDetails = `File path: ${csvPath}<br><br>${formattedDetails}`;
        }
        detailsElement.innerHTML = formattedDetails;
    } else {
        detailsElement.innerHTML = `File path: ${csvPath}<br>No detailed error information provided`;
    }
    
    // Automatically hide details
    detailsElement.style.display = 'none';
}

// Update iteration display
function updateIterationDisplay() {
    document.getElementById('current-iter').textContent = currentIteration;
    document.getElementById('iter-pred-1').value = currentPredIter1;
    document.getElementById('iter-pred-2').value = currentPredIter2;
    document.getElementById('total-iters').textContent = itermax;
    document.getElementById('pred-range-1').textContent = `1 - ${predImageMaxIter}`;
    document.getElementById('pred-range-2').textContent = `1 - ${predImageMaxIter}`;
}

// Update all images
function updateAllImages() {
    // Use Promise to ensure image loading state is controllable
    updateMainImage()
        .then(() => console.log('Main image loading complete'))
        .catch(err => console.error('Main image loading failed:', err));
        
    updatePredImage(1, currentPredIter1)
        .then(() => console.log('Prediction image 1 loading complete'))
        .catch(err => console.error('Prediction image 1 loading failed:', err));
        
    updatePredImage(2, currentPredIter2)
        .then(() => console.log('Prediction image 2 loading complete'))
        .catch(err => console.error('Prediction image 2 loading failed:', err));
        
    updateOtherTabImages(currentIteration);
}

// Update main image - using cache mechanism
function updateMainImage() {
    return new Promise((resolve, reject) => {
        if (!phaseName) {
            reject(new Error('Phase name not obtained'));
            return;
        }
        
        // Display loading state
        const loadingElement = document.getElementById('main-loading');
        const imageElement = document.getElementById('main-image');
        const pathElement = document.getElementById('main-image-path');
        const statusElement = document.getElementById('main-image-status');
        const cacheIndicator = document.getElementById('main-image-cache');
        
        loadingElement.style.display = 'block';
        imageElement.style.display = 'none';
        statusElement.style.display = 'block';
        statusElement.textContent = 'Loading...';
        cacheIndicator.style.display = 'none';
        
        // Build image URL, including phase name
        const formattedIter = String(currentIteration).padStart(4, '0');
        const baseImageUrl = `${IMAGE_BASE_PATH}iter.png`;
        
        // Check cache
        const cachedImage = getImageFromCache(baseImageUrl);
        if (cachedImage) {
            // Use cached image
            imageElement.src = cachedImage.data;
            loadingElement.style.display = 'none';
            imageElement.style.display = 'block';
            statusElement.textContent = 'Loading Complete';
            cacheIndicator.style.display = 'block';
            pathElement.textContent = `Image path: ${baseImageUrl} (Cached)`;
            console.log('Using cache to load main image:', baseImageUrl);
            resolve();
            return;
        }
        
        // Add timestamp to avoid caching
        const timestamp = new Date().getTime();
        const imageUrl = `${baseImageUrl}?timestamp=${timestamp}`;
        
        // Display image path
        pathElement.textContent = `Image path: ${baseImageUrl}`;
        
        // Clear previous event listeners
        imageElement.onload = null;
        imageElement.onerror = null;
        
        // Clear previous image source to ensure reload
        imageElement.src = '';
        
        // Create image object for preloading
        const img = new Image();
        
        // Set timeout to 20 seconds
        const timeout = setTimeout(() => {
            statusElement.textContent = 'Loading timeout, retrying...';
            
            // Retry reload after first timeout
            img.src = '';
            setTimeout(() => {
                const newTimestamp = new Date().getTime();
                img.src = `${baseImageUrl}?timestamp=${newTimestamp}`;
            }, 1000);
            
            // Show error on second timeout
            const secondTimeout = setTimeout(() => {
                loadingElement.innerHTML = `
                    <i class="fas fa-exclamation-triangle text-warning fa-3x"></i>
                    <p class="mt-2">Image loading timeout</p>
                    <p class="text-muted">Please check network connection or file path</p>
                    <button class="btn btn-sm btn-primary mt-2" onclick="updateMainImage()">Retry</button>
                `;
                statusElement.style.display = 'none';
                reject(new Error('Image loading timeout'));
            }, 20000);
            
            // If second load succeeds, clear second timeout
            img.onload = function() {
                clearTimeout(secondTimeout);
                // Convert to dataURL and save to cache
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
                statusElement.textContent = 'Loading Complete';
                console.log('Comprehensive training metrics view loaded successfully (after retry)');
                resolve();
            };
        }, 20000);
        
        // Image loading success
        img.onload = function() {
            clearTimeout(timeout);
            
            // Convert to dataURL and save to cache
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
            statusElement.textContent = 'Loading Complete';
            console.log('Comprehensive training metrics view loaded successfully');
            resolve();
        };
        
        img.onerror = function(error) {
            clearTimeout(timeout);
            console.error('Comprehensive training metrics view loading failed:', error);
            loadingElement.innerHTML = `
                <i class="fas fa-exclamation-triangle text-warning fa-3x"></i>
                <p class="mt-2">Image loading failed</p>
                <p class="text-muted">Please check if file exists: ${baseImageUrl}</p>
                <button class="btn btn-sm btn-primary mt-2" onclick="updateMainImage()">Retry</button>
            `;
            statusElement.style.display = 'none';
            reject(error);
        };
        
        // Attempt to load image
        img.src = imageUrl;
    });
}

// Update prediction image - using cache mechanism
function updatePredImage(processNum, iter) {
    console.log(`Updating prediction image ${processNum}, iteration: ${iter} in ${predImageMinIter} - ${predImageMaxIter}`);
    return new Promise((resolve, reject) => {
        if (!phaseName) {
            reject(new Error('Phase name not obtained'));
            return;
        }

        
        // Ensure iteration is within valid range
        if (iter < predImageMinIter || iter > predImageMaxIter || predImageMaxIter === 0) {
            reject(new Error('Iteration value out of valid range'));
            return;
        }
        
        // Update current iteration
        if (processNum === 1) {
            currentPredIter1 = iter;
            document.getElementById('iter-pred-1').value = iter;
        } else {
            currentPredIter2 = iter;
            document.getElementById('iter-pred-2').value = iter;
        }
        
        // Display loading state
        const loadingElement = document.getElementById(`pred-loading-${processNum}`);
        const imageElement = document.getElementById(`pred-image-${processNum}`);
        const pathElement = document.getElementById(`pred-image-path-${processNum}`);
        const statusElement = document.getElementById(`pred-image-status-${processNum}`);
        const cacheIndicator = document.getElementById(`pred-image-cache-${processNum}`);
        
        loadingElement.style.display = 'block';
        imageElement.style.display = 'none';
        statusElement.style.display = 'block';
        statusElement.textContent = 'Loading...';
        cacheIndicator.style.display = 'none';
        
        // Build image URL, including phase name, process fixed at 2
        const formattedIter = String(iter).padStart(4, '0');
        const baseImageUrl = `${IMAGE_BASE_PATH}pred_test_${phaseName}_iter${formattedIter}_process2.png`;
        
        // Check cache
        const cachedImage = getImageFromCache(baseImageUrl);
        if (cachedImage) {
            // Use cached image
            imageElement.src = cachedImage.data;
            loadingElement.style.display = 'none';
            imageElement.style.display = 'block';
            statusElement.textContent = 'Loading Complete';
            cacheIndicator.style.display = 'block';
            pathElement.textContent = `Image path: ${baseImageUrl} (Cached)`;
            console.log(`Using cache to load prediction image ${processNum}:`, baseImageUrl);
            
            // Update R² value from CSV data
            if (csvData.length > 0) {
                const r2Element = document.getElementById(`pred-r2-${processNum}`);
                // Iterations start from 1, array index starts from 0
                const index = Math.min(iter - 1, csvData.length - 1);
                let r2Value = null;
                if (index >= 0) {
                    r2Value = csvData[index].r2Score;
                }
                // If no corresponding value, use the last one
                if (r2Value === null && csvData.length > 0) {
                    r2Value = csvData[csvData.length - 1].r2Score;
                }
                r2Element.textContent = r2Value !== null ? 
                    `R²: ${r2Value.toFixed(3)}` : 'R²: N/A';
            }
            
            resolve();
            return;
        }
        
        // Add timestamp to avoid caching
        const timestamp = new Date().getTime();
        const imageUrl = `${baseImageUrl}?timestamp=${timestamp}`;
        
        // Display image path
        pathElement.textContent = `Image path: ${baseImageUrl}`;
        
        // Clear previous event listeners
        imageElement.onload = null;
        imageElement.onerror = null;
        
        // Create image object for preloading
        const img = new Image();
        
        // Set timeout to 20 seconds
        const timeout = setTimeout(() => {
            statusElement.textContent = 'Loading timeout, retrying...';
            
            // Retry reload after first timeout
            img.src = '';
            setTimeout(() => {
                const newTimestamp = new Date().getTime();
                img.src = `${baseImageUrl}?timestamp=${newTimestamp}`;
            }, 1000);
            
            // Show error on second timeout
            const secondTimeout = setTimeout(() => {
                loadingElement.innerHTML = `
                    <i class="fas fa-exclamation-triangle text-warning fa-3x"></i>
                    <p class="mt-2">Image loading timeout</p>
                    <p class="text-muted">Please check if file exists: ${baseImageUrl}</p>
                    <button class="btn btn-sm btn-primary mt-2" onclick="updatePredImage(${processNum}, ${iter})">Retry</button>
                `;
                statusElement.style.display = 'none';
                reject(new Error('Image loading timeout'));
            }, 20000);
            
            // If second load succeeds, clear second timeout
            img.onload = function() {
                clearTimeout(secondTimeout);
                // Convert to dataURL and save to cache
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
                statusElement.textContent = 'Loading Complete';
                
                // Update R² value
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
        
        // Image loading success
        img.onload = function() {
            clearTimeout(timeout);
            
            // Convert to dataURL and save to cache
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
            statusElement.textContent = 'Loading Complete';
            
            // Update R² value
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
                <p class="mt-2">Image loading failed</p>
                <p class="mt-2">Please check if file exists: ${baseImageUrl}</p>
                <button class="btn btn-sm btn-primary mt-2" onclick="updatePredImage(${processNum}, ${iter})">Retry</button>
            `;
            statusElement.style.display = 'none';
            reject(new Error('Image loading failed'));
        };
        
        // Attempt to load image
        img.src = imageUrl;
    });
}

// Update images in other tabs
function updateOtherTabImages(iter) {
    // Ensure iteration is within valid range
    if (iter < 1 || iter > totalIterations || totalIterations === 0 || !phaseName) return;
    
    // Update convex hull info image
    updateTabImage('convex-hull', iter, 'convex_hull');
    
    // Update feature analysis image
    updateTabImage('features', iter, 'features_importance');
    
    // Update log info image
    updateTabImage('logs', iter, 'training_logs');
}

// Update image for specified tab
function updateTabImage(tabId, iter, imagePrefix) {
    const loadingElement = document.getElementById(`${tabId}-loading`);
    const imageElement = document.getElementById(`${tabId}-image`);
    const pathElement = document.getElementById(`${tabId}-image-path`);
    const cacheIndicator = document.getElementById(`${tabId}-cache`);
    
    if (!loadingElement || !imageElement || !pathElement) return;
    
    // Display loading state
    loadingElement.style.display = 'block';
    imageElement.style.display = 'none';
    cacheIndicator.style.display = 'none';
    
    // Build image URL, including phase name
    const formattedIter = String(iter).padStart(4, '0');
    const baseImageUrl = `${IMAGE_BASE_PATH}${imagePrefix}_${phaseName}_iter${formattedIter}_process2.png`;
    
    // Check cache
    const cachedImage = getImageFromCache(baseImageUrl);
    if (cachedImage) {
        // Use cached image
        imageElement.src = cachedImage.data;
        loadingElement.style.display = 'none';
        imageElement.style.display = 'block';
        cacheIndicator.style.display = 'block';
        pathElement.textContent = `Image path: ${baseImageUrl} (Cached)`;
        console.log(`Using cache to load ${tabId} image:`, baseImageUrl);
        return;
    }
    
    // Add timestamp to avoid caching
    const timestamp = new Date().getTime();
    const imageUrl = `${baseImageUrl}?timestamp=${timestamp}`;
    
    // Display image path
    pathElement.textContent = `Image path: ${baseImageUrl}`;
    
    // Clear previous event listeners
    imageElement.onload = null;
    imageElement.onerror = null;
    
    // Create image object for preloading
    const img = new Image();
    
    // Set timeout
    const timeout = setTimeout(() => {
        loadingElement.innerHTML = `
            <i class="fas fa-exclamation-triangle text-warning fa-3x"></i>
            <p class="mt-2">Image loading timeout</p>
            <p class="mt-2">Please check network connection or file path</p>
            <button class="btn btn-sm btn-primary mt-2" onclick="updateTabImage('${tabId}', ${iter}, '${imagePrefix}')">Retry</button>
        `;
    }, 20000);
    
    // Image loading success
    img.onload = function() {
        clearTimeout(timeout);
        
        // Convert to dataURL and save to cache
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
            <p class="mt-2">Image loading failed</p>
            <p class="mt-2">Please check if file exists: ${baseImageUrl}</p>
            <button class="btn btn-sm btn-primary mt-2" onclick="updateTabImage('${tabId}', ${iter}, '${imagePrefix}')">Retry</button>
        `;
    };
    
    img.src = imageUrl;
}

// Switch iteration
function changeIteration(iter) {
    if (iter < 1 || iter > totalIterations || totalIterations === 0) return;
    console.log(`Attempting to switch to: ${iter}, current max range: ${totalIterations}`);
    if (iter < 1 || iter > totalIterations || totalIterations === 0) {
        console.warn("Switch failed: out of range or data not ready");
        return;
    }
    currentIteration = iter;
    updateIterationDisplay();
    // Update metrics from CSV
    updateMetricsFromCsv();
    // Update all related images
    updateAllImages();
}