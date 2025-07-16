

import psutil
import serial
import time
import sys
import subprocess
from datetime import datetime
import requests
import json
import asyncio
import random
import string
import aiohttp
from yandex_music import ClientAsync

# --- Настройки подключения к Arduino ---
arduino_port = "/dev/ttyACM0"  # Измените это на ваш порт Arduino
baud_rate = 9000               # Должен совпадать с Arduino!

# --- Глобальная переменная для последовательного порта ---
ser = None
try:
    ser = serial.Serial(arduino_port, baud_rate, timeout=0.1)
    time.sleep(2)
    print(f"Connected to Arduino on port {arduino_port}")
except serial.SerialException:
    print(f"Error: Could not connect to Arduino on port {arduino_port}.")
    print("Ensure Arduino is connected and you selected the correct port.")
    print("You might need to add your user to the 'dialout' group: sudo usermod -a -G dialout $USER")
    print("After that, reboot or log out and log in again.")
    sys.exit(1)

# --- Настройки OpenWeatherMap API ---
OPENWEATHER_API_KEY = "OPENWEATHER_API_KEY"  # ВАШ API-КЛЮЧ
CITY_ID = "CITY_ID"                          # ВАШ ID ГОРОДА

# --- Глобальные переменные для погоды ---
weather_data = {"description": "Unknown", "temperature": 0}
weather_status = "READY"

# --- Настройки автообновления погоды ---
WEATHER_UPDATE_INTERVAL_MINUTES = 15
last_weather_api_update_time = 0

# --- Таймер для периодической отправки "пульса" в режиме ожидания ---
last_idle_data_send_time = 0
IDLE_DATA_SEND_INTERVAL_SEC = 3

# --- Настройки Яндекс.Музыки ---
YANDEX_MUSIC_TOKEN = "YANDEX_MUSIC_TOKEN" # <--- Ваш токен здесь!
MUSIC_API_CHECK_INTERVAL_SEC = 5
MUSIC_SCROLL_SPEED_SEC = 0.6 # <--- ИЗМЕНЕНО: теперь прокрутка каждые 0.2 секунды

# --- Глобальные переменные для статуса музыки ---
current_track_info = {
    "is_playing": False,
    "is_paused": False,
    "artist": "",
    "title": "",
    "full_string": "",
    "scroll_offset": 0,
    "last_scroll_time": 0
}
last_music_api_check_time = 0

# --- Вспомогательные функции ---
def bytes_to_gb(bytes_value):
    return round(bytes_value / (1024**3), 1)

def get_system_stats():
    cpu_percent = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()
    ram_used_gb = bytes_to_gb(ram.used)
    disk = psutil.disk_usage('/')
    disk_used_gb = bytes_to_gb(disk.used)
    disk_total_gb = bytes_to_gb(disk.total)
    cpu_ram_str = f"CPU:{cpu_percent:2.0f}% RAM:{ram_used_gb:4.1f}"
    cpu_ram_str = cpu_ram_str.ljust(16)[:16]
    rom_str = f"ROM:{disk_used_gb:4.1f}GB/{disk_total_gb:4.1f}GB"
    rom_str = rom_str.ljust(16)[:16]
    return cpu_ram_str, rom_str

def get_network_info(interface="wlan0"):
    ssid = "No Network"
    ip_address = "No IP"
    try:
        nmcli_output = subprocess.check_output(['nmcli', 'dev', 'show', interface], text=True, stderr=subprocess.DEVNULL)
        for line in nmcli_output.splitlines():
            if "GENERAL.CONNECTION" in line:
                conn_name_raw = line.split(':')[-1].strip()
                if conn_name_raw:
                    try:
                        ssid_output = subprocess.check_output(['nmcli', '-t', '-f', 'ssid', 'con', 'show', conn_name_raw], text=True, stderr=subprocess.DEVNULL)
                        ssid = ssid_output.strip()
                        if not ssid: ssid = conn_name_raw
                    except subprocess.CalledProcessError: ssid = conn_name_raw
                else: ssid = "No Network"
            if "IP4.ADDRESS" in line:
                ip_raw = line.split(':')[-1].strip()
                if '/' in ip_raw: ip_address = ip_raw.split('/')[0]
                else: ip_address = ip_raw
            if "IP6.ADDRESS" in line:
                ip6_raw = line.split(':')[-1].strip()
                if ip6_raw and ip_address == "No IP":
                    if '/' in ip6_raw: ip_address = ip6_raw.split('/')[0]
                    else: ip_address = ip6_raw
    except (subprocess.CalledProcessError, FileNotFoundError):
        ssid = "Error cmd"
        ip_address = "Error cmd"
    except Exception as e:
        ssid = f"Err: {e}"
        ip_address = f"Err: {e}"

    print(f"DEBUG: get_network_info returning: SSID='{ssid}', IP='{ip_address}'")

    ssid_str = f"WIFI:{ssid}"
    ssid_str = ssid_str.ljust(16)[:16]
    ip_str = ip_address
    ip_str = ip_str.ljust(16)[:16]
    return ssid_str, ip_str

def get_current_time_and_date_compact():
    now = datetime.now()
    date_str = now.strftime("%d/%m")
    time_str = now.strftime("%H:%M")
    return date_str, time_str

def get_current_time_and_date_full():
    now = datetime.now()
    date_str = now.strftime("%d/%m/%y")
    time_str = now.strftime("%H:%M")

    spaces = 16 - len(date_str) - len(time_str)
    if spaces < 1: spaces = 1
    line1 = f"{date_str}{' ' * spaces}{time_str}"
    return line1.ljust(16)[:16]

# --- Функции для погоды ---
def update_weather_data_func():
    global weather_data, weather_status, last_weather_api_update_time
    weather_status = "UPDATING"
    print("Updating weather data...")
    url = f"http://api.openweathermap.org/data/2.5/weather?id={CITY_ID}&appid={OPENWEATHER_API_KEY}&units=metric&lang=en"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        temp = round(data['main']['temp'])
        description_raw = data['weather'][0]['description']

        description_map = {
            "clear sky": "Clear",
            "few clouds": "P Cloudy",
            "scattered clouds": "Cloudy",
            "broken clouds": "Cloudy",
            "overcast clouds": "Overcast",
            "shower rain": "Showr Rain",
            "rain": "Rain",
            "light rain": "L Rain",
            "moderate rain": "M Rain",
            "heavy intensity rain": "H Rain",
            "thunderstorm": "Storm",
            "snow": "Snow",
            "mist": "Mist",
            "mists": "Mist",
            "fog": "Fog",
            "haze": "Haze",
            "sleet": "Sleet",
            "light shower snow": "L Sh Snow",
            "heavy shower snow": "H Sh Snow",
            "rain and snow": "Rain/Snow"
        }

        description = description_map.get(description_raw.lower(), description_raw).replace(' ', '')
        description = description[:10]

        weather_data["description"] = description
        weather_data["temperature"] = temp
        weather_status = "READY"
        last_weather_api_update_time = time.time()
        print(f"Weather updated: {description}, {temp}°C")
    except requests.exceptions.RequestException as e:
        weather_status = "FAILED"
        print(f"Error updating weather: {e}")
        weather_data["description"] = "Failed"
        weather_data["temperature"] = -999
    except json.JSONDecodeError:
        weather_status = "FAILED"
        print("Error decoding weather JSON response.")
        weather_data["description"] = "JSON Err"
        weather_data["temperature"] = -999
    except KeyError as e:
        weather_status = "FAILED"
        print(f"Error parsing weather data (missing key): {e}")
        weather_data["description"] = "Parse Err"
        weather_data["temperature"] = -999

def get_weather_line_for_display():
    if weather_status == "UPDATING":
        return "Updating..."
    elif weather_status == "FAILED":
        return "Weather Failed!"
    else:
        desc = weather_data["description"]
        temp = weather_data["temperature"]
        temp_str = f"{temp:+d}C"

        available_space = 16 - len(desc) - len(temp_str)
        if available_space < 1:
            desc = desc[:(16 - len(temp_str) - 1)]
            available_space = 16 - len(desc) - len(temp_str)

        weather_line = f"{desc}{' ' * available_space}{temp_str}"
        return weather_line.ljust(16)[:16]

# --- Функция транслитерации кириллицы в латиницу ---
def transliterate_cyrillic(text):
    """
    Транслитерирует русский текст в латиницу.
    Использует упрощенные правила.
    """
    mapping = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch',
        'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
    }
    trans_text = ""
    for char in text:
        trans_text += mapping.get(char, char)
    return trans_text


# --- Функции из ymnow.py (адаптированные) ---
async def get_current_track_ym(client_ym, token):
    device_info = {
        "app_name": "Chrome",
        "type": 1,
    }

    ws_proto = {
        "Ynison-Device-Id": "".join(
            [random.choice(string.ascii_lowercase) for _ in range(16)]
        ),
        "Ynison-Device-Info": json.dumps(device_info),
    }

    timeout = aiohttp.ClientTimeout(total=15, connect=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(
                url="wss://ynison.music.yandex.ru/redirector.YnisonRedirectService/GetRedirectToYnison",
                headers={
                    "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(ws_proto)}",
                    "Origin": "http://music.yandex.ru",
                    "Authorization": f"OAuth {token}",
                },
                timeout=10,
            ) as ws:
                recv = await ws.receive()
                data = json.loads(recv.data)

            if "redirect_ticket" not in data or "host" not in data:
                return {"success": False}

            new_ws_proto = ws_proto.copy()
            new_ws_proto["Ynison-Redirect-Ticket"] = data["redirect_ticket"]

            to_send = {
                "update_full_state": {
                    "player_state": {
                        "player_queue": {
                            "current_playable_index": -1,
                            "entity_id": "",
                            "entity_type": "VARIOUS",
                            "playable_list": [],
                            "options": {"repeat_mode": "NONE"},
                            "entity_context": "BASED_ON_ENTITY_BY_DEFAULT",
                            "version": {
                                "device_id": ws_proto["Ynison-Device-Id"],
                                "version": 9021243204784341000,
                                "timestamp_ms": 0,
                            },
                            "from_optional": "",
                        },
                        "status": {
                            "duration_ms": 0,
                            "paused": True,
                            "playback_speed": 1,
                            "progress_ms": 0,
                            "version": {
                                "device_id": ws_proto["Ynison-Device-Id"],
                                "version": 8321822175199937000,
                                "timestamp_ms": 0,
                            },
                        },
                    },
                    "device": {
                        "capabilities": {
                            "can_be_player": True,
                            "can_be_remote_controller": False,
                            "volume_granularity": 16,
                        },
                        "info": {
                            "device_id": ws_proto["Ynison-Device-Id"],
                            "type": "WEB",
                            "title": "Chrome Browser",
                            "app_name": "Chrome",
                        },
                        "volume_info": {"volume": 0},
                        "is_shadow": True,
                    },
                    "is_currently_active": False,
                },
                "rid": "ac281c26-a047-4419-ad00-e4fbfda1cba3",
                "player_action_timestamp_ms": 0,
                "activity_interception_type": "DO_NOT_INTERCEPT_BY_DEFAULT",
            }

            async with session.ws_connect(
                url=f"wss://{data['host']}/ynison_state.YnisonStateService/PutYnisonState",
                headers={
                    "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(new_ws_proto)}",
                    "Origin": "http://music.yandex.ru",
                    "Authorization": f"OAuth {token}",
                },
                timeout=10,
                method="GET",
            ) as ws:
                await ws.send_str(json.dumps(to_send))
                recv = await asyncio.wait_for(ws.receive(), timeout=10)
                ynison = json.loads(recv.data)

                track_index = ynison["player_state"]["player_queue"]["current_playable_index"]
                is_paused = ynison["player_state"]["status"]["paused"]

                if track_index == -1:
                    return {"success": False, "is_paused": is_paused}

                track = ynison["player_state"]["player_queue"]["playable_list"][track_index]

            await session.close()
            track_full_info = await client_ym.tracks(track["playable_id"])
            return {
                "paused": is_paused,
                "track": track_full_info,
                "success": True,
            }

    except Exception as e:
        return {"success": False, "error": str(e), "track": None}


# --- Асинхронные задачи ---

async def weather_update_task():
    global last_weather_api_update_time
    while True:
        current_time = time.time()
        if (current_time - last_weather_api_update_time) > (WEATHER_UPDATE_INTERVAL_MINUTES * 60) or weather_status == "FAILED":
            update_weather_data_func()
        await asyncio.sleep(60)

async def music_status_update_task():
    global current_track_info, last_music_api_check_time

    ym_client = ClientAsync(YANDEX_MUSIC_TOKEN)
    try:
        await ym_client.init()
    except Exception as e:
        print(f"Failed to initialize Yandex Music client: {e}")
        current_track_info["is_playing"] = False
        current_track_info["full_string"] = "YM Client Error!"
        while True:
            await asyncio.sleep(MUSIC_API_CHECK_INTERVAL_SEC)

    while True:
        current_time = time.time()

        if (current_time - last_music_api_check_time) > MUSIC_API_CHECK_INTERVAL_SEC:
            res = await get_current_track_ym(ym_client, YANDEX_MUSIC_TOKEN)

            if res["success"] and not res["paused"]:
                track = res["track"][0]
                artist_names = ", ".join([artist["name"] for artist in track["artists"]])
                title = track["title"]

                transliterated_artist = transliterate_cyrillic(artist_names)
                transliterated_title = transliterate_cyrillic(title)

                full_text = f"{transliterated_artist} - {transliterated_title}"
                if len(full_text) > 16:
                    full_text = full_text + "         "

                if current_track_info["title"] != transliterated_title or current_track_info["artist"] != transliterated_artist:
                    current_track_info["scroll_offset"] = 0

                current_track_info["is_playing"] = True
                current_track_info["is_paused"] = False
                current_track_info["artist"] = transliterated_artist
                current_track_info["title"] = transliterated_title
                current_track_info["full_string"] = full_text
            else:
                current_track_info["is_playing"] = False
                current_track_info["is_paused"] = res.get("paused", False)
                current_track_info["artist"] = ""
                current_track_info["title"] = ""
                current_track_info["full_string"] = ""
                current_track_info["scroll_offset"] = 0

            last_music_api_check_time = current_time

        if current_track_info["is_playing"] and len(current_track_info["full_string"]) > 16:
            current_time = time.time()
            if (current_time - current_track_info["last_scroll_time"]) > MUSIC_SCROLL_SPEED_SEC:
                current_track_info["scroll_offset"] = (current_track_info["scroll_offset"] + 1) % len(current_track_info["full_string"])
                current_track_info["last_scroll_time"] = current_time
        elif not current_track_info["is_playing"]:
            current_track_info["scroll_offset"] = 0

        await asyncio.sleep(0.1)

async def arduino_communication_task():
    global ser, current_track_info, last_idle_data_send_time

    if ser is None:
        print("Serial port not initialized. Exiting arduino_communication_task.")
        return

    while True:
        try:
            current_time = time.time()
            if (current_time - last_idle_data_send_time) > IDLE_DATA_SEND_INTERVAL_SEC:
                line1_to_send = ""
                line2_to_send = ""

                if current_track_info["is_playing"]:
                    date_str_compact, time_str_compact = get_current_time_and_date_compact()
                    temp_str = f"{weather_data['temperature']:+d}C"

                    line1_to_send = f"{date_str_compact} {time_str_compact} {temp_str}".ljust(16)[:16]

                    scroll_len = 16
                    full_str = current_track_info["full_string"]
                    offset = current_track_info["scroll_offset"]

                    if len(full_str) > scroll_len:
                        display_str = full_str[offset:] + full_str[:offset]
                        line2_to_send = display_str[:scroll_len]
                    else:
                        line2_to_send = full_str.ljust(scroll_len)[:scroll_len]

                else:
                    line1_to_send = get_current_time_and_date_full()
                    line2_to_send = get_weather_line_for_display()

                ser.write(f"IDLE:{line1_to_send}\n".encode('utf-8'))
                ser.write(f"IDLE:{line2_to_send}\n".encode('utf-8'))

                last_idle_data_send_time = current_time

            if ser.in_waiting > 0:
                command = ser.readline().decode('utf-8').strip()
                print(f"Received command from Arduino: '{command}'")

                if command == "REQ_WEATHER" or command == "REQ_WEATHER_FORCE":
                    update_weather_data_func()
                    print(f"Weather update requested by Arduino. Data will be sent in next IDLE pulse.")

                elif command == "REQ_SYSTEM_STATS":
                    line1, line2 = get_system_stats()
                    ser.write(f"{line1}\n".encode('utf-8'))
                    ser.write(f"{line2}\n".encode('utf-8'))
                    print(f"Sent: '{line1}', '{line2}' (System Stats)")

                elif command == "REQ_NETWORK_INFO":
                    line1, line2 = get_network_info("wlan0")
                    ser.write(f"{line1}\n".encode('utf-8'))
                    ser.write(f"{line2}\n".encode('utf-8'))
                    print(f"Sent: '{line1}', '{line2}' (Network Info)")

        except serial.SerialException as e:
            print(f"Serial communication error: {e}")
            break
        except Exception as e:
            print(f"Error in communication task: {e}")
            break

        await asyncio.sleep(0.01)

# --- Главная функция запуска асинхронных задач ---
async def main():
    if YANDEX_MUSIC_TOKEN == "YOUR_YANDEX_MUSIC_TOKEN_HERE":
        print("\nWARNING: Please set your Yandex Music Token in the script!")
        print("Instructions to get the token: https://github.com/MarshalX/yandex-music-api/discussions/513#discussioncomment-2729781\n")

    await asyncio.gather(
        weather_update_task(),
        music_status_update_task(),
        arduino_communication_task()
    )

# --- Запуск программы ---
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram terminated by user.")
    finally:
        if ser and ser.is_open:
            ser.close()
            print("Connection to Arduino closed.")
