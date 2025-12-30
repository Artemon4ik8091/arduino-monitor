#include <LiquidCrystal.h>

// Инициализация библиотеки с номерами пинов интерфейса
LiquidCrystal lcd(12, 11, 5, 4, 3, 2);

// --- Настройки кнопок ---
const int BUTTON_A_PIN = 6; // Пин для кнопки A (Принудительное обновление погоды / Возврат из статистики)
const int BUTTON_B_PIN = 7; // Пин для кнопки B (Показать системные данные + сеть)

// --- Переменные для обработки кнопок ---
int buttonAState = 0;           
int lastButtonAState = 0;       
unsigned long lastButtonAPressTime = 0; 
const long DEBOUNCE_DELAY = 50; 

int buttonBState = 0;           
int lastButtonBState = 0;       
unsigned long lastButtonBPressTime = 0; 

// --- Переменные для режима отображения ---
// 0: Режим ожидания (Дата/Время + Погода)
// 1: Режим прокрутки системной статистики (CPU/RAM/ROM -> Network Info)
int displayMode = 0; // Начинаем в режиме ожидания

// --- Подрежим для прокрутки статистики ---
// 0: Показываем CPU/RAM/ROM
// 1: Показываем Network Info
int statsSubMode = 0;

// --- Переменные для таймаута соединения ---
unsigned long last_data_received_time = 0;
const long CONNECTION_TIMEOUT = 4000; // 4 секунды
boolean connection_active = false;

// --- Буфер для хранения последних полученных данных ---
String current_weather_line1 = ""; // Дата/Время
String current_weather_line2 = ""; // Погода
String current_system_line1 = "";  // CPU/RAM
String current_system_line2 = "";  // ROM
String current_network_line1 = ""; // SSID
String current_network_line2 = ""; // IP

// --- Таймеры для Arduino ---
unsigned long last_weather_request_time = 0;
const long WEATHER_UPDATE_INTERVAL_ARDUINO_MS = 15 * 60 * 1000; // 15 минут в миллисекундах

unsigned long stats_display_start_time = 0;
const long SINGLE_CARD_DISPLAY_DURATION_MS = 5 * 1000; // 5 секунд для показа каждой карточки статистики

void setup() {
  lcd.begin(16, 2);
  lcd.print("Waiting for PC...");
  Serial.begin(9000); 
  
  pinMode(BUTTON_A_PIN, INPUT_PULLUP); 
  pinMode(BUTTON_B_PIN, INPUT_PULLUP); 

  last_data_received_time = millis(); // Инициализируем таймер соединения

  // Запрашиваем первую погоду при старте
  Serial.print("REQ_WEATHER\n"); 
  last_weather_request_time = millis();
}

void loop() {
  // --- Обработка кнопок ---
  // Кнопка A (PULLUP): нажата когда LOW
  int readingA = digitalRead(BUTTON_A_PIN);
  if (readingA != lastButtonAState) {
    lastButtonAPressTime = millis();
  }
  if ((millis() - lastButtonAPressTime) > DEBOUNCE_DELAY) {
    if (readingA != buttonAState) {
      buttonAState = readingA;
      if (buttonAState == LOW) { // Кнопка А нажата
        if (displayMode == 0) { // В режиме ожидания: принудительное обновление погоды
            Serial.print("REQ_WEATHER_FORCE\n"); 
            lcd.clear(); 
            lcd.setCursor(0,0); lcd.print("Updating weather");
            lcd.setCursor(0,1); lcd.print("Please wait...");
        } else if (displayMode == 1) { // В режиме прокрутки статистики: вернуться в ожидание
            displayMode = 0;
            statsSubMode = 0; // Сбрасываем подрежим
            if (current_weather_line1.length() > 0) { // Показываем сразу погоду, если есть
                lcd.clear();
                lcd.setCursor(0, 0); lcd.print(current_weather_line1);
                lcd.setCursor(0, 1); lcd.print(current_weather_line2);
            } else { // Иначе запросим
                Serial.print("REQ_WEATHER\n");
                lcd.clear(); lcd.print("Loading weather");
            }
        }
      }
    }
  }
  lastButtonAState = readingA;

  // Кнопка B (PULLUP): нажата когда LOW
  int readingB = digitalRead(BUTTON_B_PIN);
  if (readingB != lastButtonBState) {
    lastButtonBPressTime = millis();
  }
  if ((millis() - lastButtonBPressTime) > DEBOUNCE_DELAY) {
    if (readingB != buttonBState) {
      buttonBState = readingB;
      if (buttonBState == LOW) { // Кнопка Б нажата
        if (displayMode != 1) { // Если не в режиме статистики, переключаемся
            displayMode = 1; // Переходим в режим прокрутки статистики
            statsSubMode = 0; // Начинаем с системных данных
            Serial.print("REQ_SYSTEM_STATS\n"); // Запрашиваем системные данные
            stats_display_start_time = millis(); // Запускаем таймер для режима статистики
            lcd.clear(); 
            lcd.setCursor(0,0); lcd.print("Loading stats..."); 
        }
      }
    }
  }
  lastButtonBState = readingB;

  // --- Автоматический запрос погоды (только в режиме ожидания) ---
  if (displayMode == 0 && (millis() - last_weather_request_time > WEATHER_UPDATE_INTERVAL_ARDUINO_MS)) {
      Serial.print("REQ_WEATHER\n");
      last_weather_request_time = millis();
      lcd.clear(); 
      lcd.setCursor(0,0); lcd.print("Updating weather");
      lcd.setCursor(0,1); lcd.print("Please wait...");
  }

  // --- Автоматическая прокрутка и возврат из режима статистики ---
  if (displayMode == 1 && (millis() - stats_display_start_time > SINGLE_CARD_DISPLAY_DURATION_MS)) {
      stats_display_start_time = millis(); // Сбрасываем таймер для следующего перехода
      statsSubMode++; // Переходим к следующему подрежиму
      
      if (statsSubMode == 1) { // Если были CPU/RAM/ROM, теперь показываем Network
          Serial.print("REQ_NETWORK_INFO\n"); // Запрашиваем сетевые данные
          lcd.clear();
          lcd.setCursor(0,0); lcd.print("Loading network...");
      } else { // После сетевой информации или если был только один режим: возвращаемся в ожидание
          displayMode = 0; 
          statsSubMode = 0; // Сбрасываем подрежим для следующего раза
          if (current_weather_line1.length() > 0) { // Показываем сразу погоду, если есть
              lcd.clear();
              lcd.setCursor(0, 0); lcd.print(current_weather_line1);
              lcd.setCursor(0, 1); lcd.print(current_weather_line2);
          } else { // Иначе запросим
              Serial.print("REQ_WEATHER\n");
              lcd.clear(); lcd.print("Loading weather");
          }
      }
  }


  // --- Обработка данных из последовательного порта ---
  if (Serial.available()) {
    last_data_received_time = millis(); // Обновляем таймер, чтобы избежать "Connection lost"
    if (!connection_active) {
      lcd.clear();
      connection_active = true;
    }

    String received_line1_raw = Serial.readStringUntil('\n'); 
    String received_line2_raw = Serial.readStringUntil('\n'); 

    String received_line1; 
    String received_line2; 

    // Проверяем, есть ли префикс "IDLE:"
    if (received_line1_raw.startsWith("IDLE:")) {
        received_line1 = received_line1_raw.substring(5); // Удаляем "IDLE:"
        received_line2 = received_line2_raw.substring(5); // Удаляем "IDLE:"
        
        current_weather_line1 = received_line1;
        current_weather_line2 = received_line2;
        
        if (displayMode == 0) { // Только если в режиме ожидания, обновляем экран
            lcd.clear();
            lcd.setCursor(0, 0); lcd.print(current_weather_line1);
            lcd.setCursor(0, 1); lcd.print(current_weather_line2);
        }
    } else { // Это обычный ответ на запрос (без "IDLE:")
        received_line1 = received_line1_raw; 
        received_line2 = received_line2_raw; 
        
        if (received_line1.startsWith("CPU:")) { // Это системные данные
            current_system_line1 = received_line1;
            current_system_line2 = received_line2;
            if (displayMode == 1 && statsSubMode == 0) { // Если мы сейчас в режиме статистики и ждем CPU
                lcd.clear(); 
                lcd.setCursor(0, 0); lcd.print(current_system_line1);
                lcd.setCursor(0, 1); lcd.print(current_system_line2);
            }
        // *** ИЗМЕНЕНО ЗДЕСЬ: "SSID:" на "WIFI:" ***
        } else if (received_line1.startsWith("WIFI:") || received_line1.startsWith("No Network") || received_line1.startsWith("Error cmd")) { // Это сетевые данные
            current_network_line1 = received_line1;
            current_network_line2 = received_line2;
            if (displayMode == 1 && statsSubMode == 1) { // Если мы сейчас в режиме статистики и ждем Network
                lcd.clear(); 
                lcd.setCursor(0, 0); lcd.print(current_network_line1);
                lcd.setCursor(0, 1); lcd.print(current_network_line2);
            }
        } else { // Предполагаем, что это ответ на запрос погоды (дата/время + погода)
            current_weather_line1 = received_line1;
            current_weather_line2 = received_line2;
            if (displayMode == 0) { // Если мы сейчас в режиме ожидания
                lcd.clear();
                lcd.setCursor(0, 0); lcd.print(current_weather_line1);
                lcd.setCursor(0, 1); lcd.print(current_weather_line2);
            }
        }
    }
  } else { // Serial.available() == false (нет данных)
    // Проверка таймаута для потери соединения с ПК
    if (millis() - last_data_received_time > CONNECTION_TIMEOUT) {
      if (connection_active || last_data_received_time == 0) { 
        lcd.clear();
        lcd.setCursor(0, 0); lcd.print("Connection lost!");
        lcd.setCursor(0, 1); lcd.print("Check PC.");
        connection_active = false;
      }
    } else {
        if (connection_active) {
            if (displayMode == 0) { 
                if (current_weather_line1.length() > 0) {
                    lcd.setCursor(0, 0); lcd.print(current_weather_line1);
                    lcd.setCursor(0, 1); lcd.print(current_weather_line2);
                } else {
                    lcd.clear(); lcd.setCursor(0,0); lcd.print("Waiting for data");
                }
            } else if (displayMode == 1) { 
                if (statsSubMode == 0 && current_system_line1.length() > 0) { 
                    lcd.setCursor(0, 0); lcd.print(current_system_line1);
                    lcd.setCursor(0, 1); lcd.print(current_system_line2);
                } else if (statsSubMode == 1 && current_network_line1.length() > 0) { 
                    lcd.setCursor(0, 0); lcd.print(current_network_line1);
                    lcd.setCursor(0, 1); lcd.print(current_network_line2);
                } else {
                    lcd.clear(); lcd.setCursor(0,0); lcd.print("Loading data...");
                }
            }
        }
    }
  }
}