const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const uploadBtn = document.getElementById('upload-btn');
const previewSection = document.getElementById('preview-section');
const originalPreview = document.getElementById('original-preview');
const resultPreview = document.getElementById('result-preview');
const loading = document.getElementById('loading');
const saveSection = document.getElementById('save-section');
const filenameInput = document.getElementById('filename-input');
const saveBtn = document.getElementById('save-btn');

let resultBlobUrl = null;
let resultBlob = null;
let originalFileName = 'image';

// Кнопка выбора файла
uploadBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    fileInput.click();
});

dropZone.addEventListener('click', () => {
    fileInput.click();
});

fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
        handleFile(fileInput.files[0]);
    }
});

// Drag & Drop
dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove('drag-over');
    const files = e.dataTransfer.files;
    if (files.length > 0 && files[0].type.startsWith('image/')) {
        handleFile(files[0]);
    }
});

// Вставка из буфера
document.addEventListener('paste', (e) => {
    const items = e.clipboardData.items;
    for (let item of items) {
        if (item.type.startsWith('image/')) {
            handleFile(item.getAsFile());
            break;
        }
    }
});

// Не даём браузеру открывать файл при дропе вне зоны
window.addEventListener('dragover', (e) => e.preventDefault(), { passive: false });
window.addEventListener('drop', (e) => e.preventDefault(), { passive: false });

function handleFile(file) {
    originalFileName = file.name;
    const reader = new FileReader();
    reader.onload = (e) => {
        originalPreview.src = e.target.result;
        previewSection.classList.remove('hidden');
        resultPreview.classList.add('hidden');
        saveSection.classList.add('hidden');
        loading.classList.remove('hidden');
        loading.innerHTML = '<div class="spinner"></div><p>Обработка...</p>';
        uploadImage(file);
    };
    reader.readAsDataURL(file);
}

async function uploadImage(file) {
    const formData = new FormData();
    formData.append('image', file);

    try {
        const response = await fetch('/remove-bg', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error('Ошибка обработки');
        }

        // ✅ только здесь работаем с картинкой
        const blob = await response.blob();

        if (resultBlobUrl) {
            URL.revokeObjectURL(resultBlobUrl);
        }
        resultBlobUrl = URL.createObjectURL(blob);
        resultBlob = blob;

        resultPreview.src = resultBlobUrl;
        resultPreview.classList.remove('hidden');
        loading.classList.add('hidden');
        saveSection.classList.remove('hidden');

        // Подставляем оригинальное имя файла
        const origName = response.headers.get('X-Original-Filename') || 'image';
        const nameWithoutExt = origName.replace(/\.[^.]+$/, '');
        filenameInput.value = nameWithoutExt + '-no-background';

        saveBtn.onclick = () => {
            let name = filenameInput.value.trim() || (nameWithoutExt + '-no-background');
            name = name.replace(/\.png$/i, '');
            const a = document.createElement('a');
            a.href = resultBlobUrl;
            a.download = name + '.png';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        };
    } catch (error) {
        console.error('Error:', error);
        loading.innerHTML = '<p style="color: #c00;">Ошибка: ' + error.message + '</p>';
    }
}
