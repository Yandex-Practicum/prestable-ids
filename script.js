const fs = require('fs');
const path = require('path');

function processDirectory(dirPath) {
  try {
    const items = fs.readdirSync(dirPath);

    for (const item of items) {
      const fullPath = path.join(dirPath, item);
      const stat = fs.statSync(fullPath);

      if (stat.isDirectory()) {
        // Рекурсивно обрабатываем поддиректории
        processDirectory(fullPath);
      } else if (stat.isFile() && path.extname(fullPath).toLowerCase() === '.json') {
        // Обрабатываем JSON файлы
        processJsonFile(fullPath);
      }
    }
  } catch (error) {
    console.error(`Ошибка при обработке директории ${dirPath}:`, error.message);
  }
}

function processJsonFile(filePath) {
  try {
    // Читаем исходный файл
    const content = fs.readFileSync(filePath, 'utf8');

    // Парсим JSON для валидации и удаления отступов
    const jsonData = JSON.parse(content);

    // Преобразуем обратно в строку без отступов
    const minifiedJson = JSON.stringify(jsonData);

    // Записываем обратно в файл
    fs.writeFileSync(filePath, minifiedJson, 'utf8');

    console.log(`Обработан файл: ${filePath}`);
  } catch (error) {
    console.error(`Ошибка при обработке файла ${filePath}:`, error.message);
  }
}

// Основная функция
function minifyAllJsonFiles(startPath = '.') {
  console.log('Начало обработки JSON файлов...');

  // Проверяем существование начальной директории
  if (!fs.existsSync(startPath)) {
    console.error(`Директория не существует: ${startPath}`);
    return;
  }

  processDirectory(startPath);
  console.log('Обработка завершена!');
}

// Использование:
// Запуск из текущей директории
minifyAllJsonFiles();

// Или указать конкретную директорию:
// minifyAllJsonFiles('/path/to/your/directory');
