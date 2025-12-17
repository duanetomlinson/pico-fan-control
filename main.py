# Same code, ready for manipulation



from machine import Pin, PWM, ADC, WDT, reset
import network
import socket
import json
import time

# ============ CONFIGURATION ============
WIFI_SSID = 'Key West'
WIFI_PASSWORD = 'HouseOfMusic'
PORT = 8080
WIFI_CHECK_INTERVAL = 30  # Check WiFi every 30 seconds
WATCHDOG_TIMEOUT = 8000   # 8 second watchdog (max on Pico)

# ============ FAN CONTROLLER ============
class FanController:
    def __init__(self, pwm_pin=18, tach_pin=17):
        self.fan = PWM(Pin(pwm_pin))
        self.fan.freq(25000)
        self.temp_sensor = ADC(4)
        self.tach = Pin(tach_pin, Pin.IN, Pin.PULL_UP)
        self.pulse_count = 0
        self.tach.irq(trigger=Pin.IRQ_FALLING, handler=self._tach_callback)
        self.rpm = 0
        self.last_rpm_check = time.ticks_ms()
        self.current_speed = 0
        self.manual_override = None
        self.start_time = time.time()
        self.error_count = 0
    
    def _tach_callback(self, pin):
        self.pulse_count += 1
    
    def get_rpm(self):
        current_time = time.ticks_ms()
        elapsed = time.ticks_diff(current_time, self.last_rpm_check)
        if elapsed >= 1000:
            self.rpm = int((self.pulse_count / 2) * (60000 / elapsed))
            self.pulse_count = 0
            self.last_rpm_check = current_time
        return self.rpm
    
    def get_temp(self):
        reading = self.temp_sensor.read_u16()
        voltage = reading * 3.3 / 65535
        return 27 - (voltage - 0.706) / 0.001721
    
    def get_uptime(self):
        secs = int(time.time() - self.start_time)
        hrs = secs // 3600
        mins = (secs % 3600) // 60
        secs = secs % 60
        return '{}h {}m {}s'.format(hrs, mins, secs)
    
    def set_manual_speed(self, speed):
        if speed is None:
            self.manual_override = None
        else:
            self.manual_override = max(0, min(100, speed))
        return self.manual_override
    
    def update(self):
        temp = self.get_temp()
        rpm = self.get_rpm()
        
        if self.manual_override is not None:
            speed = self.manual_override
        else:
            if temp < 30:
                speed = 10
            elif temp < 40:
                speed = 40
            elif temp < 50:
                speed = 50
            elif temp < 60:
                speed = 60
            elif temp < 70:
                speed = 70
            else:
                speed = 100
        
        if speed != self.current_speed:
            self.current_speed = speed
            duty = int((speed / 100) * 65535)
            self.fan.duty_u16(duty)
        
        return temp, speed, rpm


# ============ WIFI MANAGER ============
class WiFiManager:
    def __init__(self, ssid, password):
        self.ssid = ssid
        self.password = password
        self.wlan = network.WLAN(network.STA_IF)
        self.last_check = 0
        self.reconnect_attempts = 0
        self.ip = None
    
    def is_connected(self):
        return self.wlan.isconnected() and self.wlan.status() == 3
    
    def connect(self, timeout=15):
        """Attempt to connect to WiFi. Non-blocking after initial attempt."""
        print('WiFi: Connecting to {}...'.format(self.ssid))
        
        self.wlan.active(True)
        
        # Disconnect first if in weird state
        if self.wlan.status() != 0 and not self.is_connected():
            self.wlan.disconnect()
            time.sleep(1)
        
        if not self.is_connected():
            self.wlan.connect(self.ssid, self.password)
            
            # Wait for connection with timeout
            start = time.time()
            while time.time() - start < timeout:
                if self.is_connected():
                    self.ip = self.wlan.ifconfig()[0]
                    self.reconnect_attempts = 0
                    print('WiFi: Connected! IP: {}'.format(self.ip))
                    return True
                time.sleep(1)
            
            print('WiFi: Connection failed (attempt {})'.format(self.reconnect_attempts + 1))
            self.reconnect_attempts += 1
            return False
        
        self.ip = self.wlan.ifconfig()[0]
        return True
    
    def check_and_reconnect(self):
        """Check WiFi status and reconnect if needed. Call periodically."""
        current_time = time.time()
        
        # Only check every WIFI_CHECK_INTERVAL seconds
        if current_time - self.last_check < WIFI_CHECK_INTERVAL:
            return self.is_connected()
        
        self.last_check = current_time
        
        if not self.is_connected():
            print('WiFi: Connection lost, reconnecting...')
            return self.connect(timeout=10)
        
        return True
    
    def get_status(self):
        """Return WiFi status info."""
        status_codes = {
            0: 'IDLE',
            1: 'CONNECTING',
            2: 'WRONG_PASSWORD',
            3: 'CONNECTED',
            -1: 'FAILED',
            -2: 'NO_AP_FOUND',
            -3: 'CONNECT_FAIL'
        }
        code = self.wlan.status()
        return {
            'connected': self.is_connected(),
            'status': status_codes.get(code, 'UNKNOWN'),
            'status_code': code,
            'ip': self.ip if self.is_connected() else None,
            'reconnect_attempts': self.reconnect_attempts
        }


# ============ ASCII ART HELPERS ============
def get_fan_ascii(speed):
    if speed < 20:
        return '''
      __
    /    \\
   |  ()  |
    \\____/
   [IDLE]'''
    elif speed < 50:
        return '''
      __
    / -- \\
   | (--) |
    \\____/
   [SLOW]'''
    elif speed < 80:
        return '''
      __
    /~||~\\
   | (><) |
    \\~~~~/
    [MED]'''
    else:
        return '''
      __
    /*||*\\
   |*(><)*|
    \\****/
    [MAX]'''


def get_bar(value, max_val, width=20):
    pct = min(100, max(0, (value / max_val) * 100))
    filled = int((pct / 100) * width)
    empty = width - filled
    return '[' + '#' * filled + '-' * empty + ']'


def get_temp_status(temp):
    if temp < 35:
        return 'COOL'
    elif temp < 50:
        return 'OK'
    elif temp < 65:
        return 'WARM'
    else:
        return 'HOT!'


# ============ HTML TEMPLATE ============
def build_html_page(controller, temp, speed, rpm, wifi_status):
    fan_art = get_fan_ascii(speed)
    temp_bar = get_bar(temp, 80)
    speed_bar = get_bar(speed, 100)
    temp_status = get_temp_status(temp)
    mode = 'MANUAL' if controller.manual_override is not None else 'AUTO'
    mode_class = 'manual' if mode == 'MANUAL' else 'auto'
    uptime = controller.get_uptime()
    wifi_indicator = 'OK' if wifi_status['connected'] else 'RECONN'
    
    html = '''<!DOCTYPE html>
<html>
<head>
    <title>Noctua Fan Controller</title>
    <meta charset="ASCII">
    <meta http-equiv="refresh" content="2">
    <style>
        body {{
            background: #1a1a2e;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            padding: 20px;
            font-size: 14px;
        }}
        .container {{
            max-width: 500px;
            margin: 0 auto;
        }}
        pre {{
            background: #16213e;
            padding: 15px;
            border: 1px solid #00ff00;
            border-radius: 5px;
            line-height: 1.4;
        }}
        .title {{
            color: #e94560;
            text-align: center;
        }}
        .fan-box {{
            text-align: center;
        }}
        .controls {{
            margin-top: 20px;
            text-align: center;
        }}
        .controls a {{
            display: inline-block;
            background: #16213e;
            color: #00ff00;
            padding: 8px 16px;
            margin: 5px;
            text-decoration: none;
            border: 1px solid #00ff00;
            border-radius: 3px;
        }}
        .controls a:hover {{
            background: #00ff00;
            color: #1a1a2e;
        }}
        .auto {{ color: #00ff00; }}
        .manual {{ color: #ffff00; }}
        .footer {{
            margin-top: 20px;
            text-align: center;
            color: #666;
            font-size: 12px;
        }}
        .footer a {{
            color: #e94560;
        }}
    </style>
</head>
<body>
    <div class="container">
        <pre class="title">
+=======================================+
|     NOCTUA FAN CONTROLLER v1.0        |
|        Raspberry Pi Pico W            |
+=======================================+
        </pre>
        
        <pre class="fan-box">{}</pre>
        
        <pre>
+---------------------------------------+
| TEMP: {:.1f}C [{}]                     |
| {}  {:.1f}C             |
+---------------------------------------+
| FAN:  {}%                             |
| {}  {}%              |
+---------------------------------------+
| RPM:  {}                              |
+---------------------------------------+
| MODE:   <span class="{}">{}</span>                         |
| UPTIME: {}                     |
| WIFI:   {} ({})                |
+---------------------------------------+
        </pre>
        
        <div class="controls">
            <div>Set Speed:</div>
            <a href="/speed?pct=10">10%</a>
            <a href="/speed?pct=30">30%</a>
            <a href="/speed?pct=50">50%</a>
            <a href="/speed?pct=70">70%</a>
            <a href="/speed?pct=100">100%</a>
            <br><br>
            <a href="/auto">AUTO MODE</a>
            <a href="/restart">RESTART</a>
        </div>
        
        <div class="footer">
            <a href="/api">JSON API</a> | Auto-refresh: 2s
        </div>
    </div>
</body>
</html>'''.format(
        fan_art,
        temp, temp_status,
        temp_bar, temp,
        speed,
        speed_bar, speed,
        rpm,
        mode_class, mode,
        uptime,
        wifi_indicator, wifi_status['status']
    )
    return html


# ============ WEB SERVER ============
def send_response(conn, body, content_type='application/json', status='200 OK'):
    response = 'HTTP/1.1 {}\r\n'.format(status)
    response += 'Content-Type: {}; charset=ascii\r\n'.format(content_type)
    response += 'Content-Length: {}\r\n'.format(len(body))
    response += 'Connection: close\r\n\r\n'
    conn.sendall(response.encode('ascii'))
    conn.sendall(body.encode('ascii'))


def create_server():
    """Create and return a new server socket."""
    addr = socket.getaddrinfo('0.0.0.0', PORT)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)
    return s


def handle_request(conn, controller, wifi_manager):
    """Handle a single HTTP request."""
    try:
        request = conn.recv(1024).decode('ascii')
    except:
        request = ''
    
    path = '/'
    if 'GET ' in request:
        path = request.split('GET ')[1].split(' ')[0]
    
    temp, speed, rpm = controller.update()
    wifi_status = wifi_manager.get_status()
    
    if path.startswith('/speed?pct='):
        try:
            pct = int(path.split('pct=')[1].split('&')[0].split(' ')[0])
            actual = controller.set_manual_speed(pct)
            body = json.dumps({'success': True, 'speed': actual, 'mode': 'manual'})
            send_response(conn, body)
        except Exception as e:
            body = json.dumps({'error': str(e)})
            send_response(conn, body, status='400 Bad Request')
    
    elif path.startswith('/auto'):
        controller.set_manual_speed(None)
        body = json.dumps({'success': True, 'mode': 'auto'})
        send_response(conn, body)
    
    elif path.startswith('/restart'):
        body = json.dumps({'success': True, 'message': 'Restarting...'})
        send_response(conn, body)
        conn.close()
        time.sleep(1)
        reset()
    
    elif path.startswith('/api') or path.startswith('/status'):
        body = json.dumps({
            'temp_c': round(temp, 1),
            'fan_pct': speed,
            'rpm': rpm,
            'mode': 'manual' if controller.manual_override is not None else 'auto',
            'uptime': controller.get_uptime(),
            'wifi': wifi_status
        })
        send_response(conn, body)
    
    else:
        body = build_html_page(controller, temp, speed, rpm, wifi_status)
        send_response(conn, body, content_type='text/html')


# ============ MAIN LOOP ============
def main():
    print('')
    print('=' * 40)
    print('Noctua Fan Controller Starting...')
    print('=' * 40)
    
    # Initialize watchdog - will reset if not fed
    wdt = WDT(timeout=WATCHDOG_TIMEOUT)
    print('Watchdog: Enabled ({}ms)'.format(WATCHDOG_TIMEOUT))
    
    # Initialize fan controller FIRST (must always run)
    controller = FanController(pwm_pin=18, tach_pin=17)
    print('Fan: Initialized')
    
    # Feed watchdog after fan init
    wdt.feed()
    
    # Initialize WiFi manager
    wifi = WiFiManager(WIFI_SSID, WIFI_PASSWORD)
    
    # Initial WiFi connection (non-fatal if fails)
    wifi.connect(timeout=15)
    wdt.feed()
    
    # Create server socket
    server = None
    if wifi.is_connected():
        try:
            server = create_server()
            print('Server: http://{}:{}/'.format(wifi.ip, PORT))
        except Exception as e:
            print('Server: Failed to start - {}'.format(e))
    
    print('=' * 40)
    print('Main loop starting...')
    print('=' * 40)
    
    error_count = 0
    last_status_print = 0
    
    while True:
        try:
            # ALWAYS feed watchdog first
            wdt.feed()
            
            # ALWAYS update fan control (this must never fail)
            try:
                temp, speed, rpm = controller.update()
            except Exception as e:
                print('CRITICAL: Fan update failed - {}'.format(e))
                error_count += 1
                if error_count > 10:
                    print('Too many fan errors, resetting...')
                    reset()
            
            # Check WiFi and reconnect if needed
            wifi_ok = wifi.check_and_reconnect()
            
            # Recreate server if WiFi reconnected and server is dead
            if wifi_ok and server is None:
                try:
                    server = create_server()
                    print('Server: Restarted on http://{}:{}/'.format(wifi.ip, PORT))
                except Exception as e:
                    print('Server: Restart failed - {}'.format(e))
            
            # Handle web requests if server is available
            if server is not None and wifi_ok:
                server.settimeout(0.5)
                try:
                    conn, addr = server.accept()
                    conn.settimeout(2.0)
                    try:
                        handle_request(conn, controller, wifi)
                    except Exception as e:
                        print('Request error: {}'.format(e))
                    finally:
                        try:
                            conn.close()
                        except:
                            pass
                except OSError:
                    # Timeout waiting for connection - normal
                    pass
                except Exception as e:
                    # Server socket error - try to recreate
                    print('Server error: {}'.format(e))
                    try:
                        server.close()
                    except:
                        pass
                    server = None
            
            # Periodic status print (every 60 seconds)
            if time.time() - last_status_print > 60:
                wifi_status = 'OK' if wifi.is_connected() else 'DISCONNECTED'
                print('Status: {:.1f}C, {}%, {} RPM, WiFi: {}'.format(
                    temp, speed, rpm, wifi_status))
                last_status_print = time.time()
            
            # Reset error count on successful loop
            error_count = 0
            
            # Small delay
            time.sleep(0.1)
            
        except KeyboardInterrupt:
            print('Interrupted by user')
            break
        except Exception as e:
            print('Loop error: {}'.format(e))
            error_count += 1
            if error_count > 5:
                print('Too many errors, resetting...')
                time.sleep(1)
                reset()
            time.sleep(1)


# ============ ENTRY POINT ============
if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('FATAL: {}'.format(e))
        time.sleep(5)
        reset()

