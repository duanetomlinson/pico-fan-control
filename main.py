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


# ============ TELEMETRY HELPERS ============
def get_temp_status(temp):
    if temp < 35:
        return 'Cool'
    elif temp < 50:
        return 'OK'
    elif temp < 65:
        return 'Warm'
    else:
        return 'Hot'


def _temp_class(temp):
    if temp < 35:
        return 'cool'
    elif temp >= 65:
        return 'hot'
    return ''


def _format_thousands(n):
    s = str(int(n))
    if len(s) <= 3:
        return s
    out = ''
    while len(s) > 3:
        out = ',' + s[-3:] + out
        s = s[:-3]
    return s + out


def _spin_seconds(speed):
    if speed < 5:
        return '0'
    return '{:.2f}'.format(3.0 - (speed / 100.0) * 2.5)


# ============ HTML TEMPLATE ============
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="theme-color" content="#FAF7F2" />
<meta http-equiv="refresh" content="2" />
<title>Pico Fan &mdash; Tomlinson Works</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' fill='%23FAF7F2'/%3E%3Ccircle cx='16' cy='16' r='6' fill='%23C96442'/%3E%3C/svg%3E" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;0,9..144,500;1,9..144,400;1,9..144,500&family=DM+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" />
<style>
:root{
  --ground:#FAF7F2;--surface:#FFFFFF;--ink:#1F1B16;--ink-soft:#44403C;
  --muted:#78716C;--rule:#E7E2D7;--rule-strong:#C8C0B0;
  --accent:#C96442;--accent-deep:#9A4A30;
  --cool:#6A8AA8;--hot:#9A4A30;--good:#6F8B5F;
  --display:"Fraunces","Times New Roman",serif;
  --body:"DM Sans",system-ui,-apple-system,sans-serif;
  --mono:"JetBrains Mono","Courier New",monospace;
  --pad-x:clamp(1.25rem,4vw,4rem);
  --section-y:clamp(2.5rem,5vw,4.5rem);
}
*{box-sizing:border-box}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--body);font-size:16px;line-height:1.55;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
p{margin:0 0 1rem}
.container{padding-left:var(--pad-x);padding-right:var(--pad-x);max-width:72rem;margin:0 auto}
section{padding-top:var(--section-y);padding-bottom:var(--section-y)}
section+section,footer{border-top:1px solid var(--rule)}
.eyebrow{font-family:var(--mono);font-size:.6875rem;letter-spacing:.25em;text-transform:uppercase;color:var(--accent);display:inline-flex;align-items:center;gap:.75rem;margin:0}
.eyebrow::before{content:"";display:inline-block;width:1.5rem;height:1px;background:var(--accent)}
.display{font-family:var(--display);letter-spacing:-.015em;line-height:1.05}
.h1{font-size:clamp(2.5rem,6vw,4.5rem);font-weight:300}
.h2{font-size:clamp(1.5rem,3vw,2.25rem);font-weight:300;line-height:1.1}
em{font-style:italic;font-weight:400}
.site-header{background:rgba(250,247,242,.92);backdrop-filter:saturate(180%) blur(8px);-webkit-backdrop-filter:saturate(180%) blur(8px);border-bottom:1px solid var(--rule)}
.nav{display:flex;align-items:center;justify-content:space-between;padding:1.25rem 0}
.wordmark{display:inline-flex;align-items:center;gap:.5rem;font-family:var(--display);font-style:italic;font-weight:500;font-size:1.25rem}
.wordmark .dot{width:6px;height:6px;background:var(--accent);border-radius:50%}
.wordmark .suffix{font-family:var(--mono);font-style:normal;font-weight:400;font-size:.6875rem;letter-spacing:.2em;text-transform:uppercase;color:var(--accent)}
.nav-meta{font-family:var(--mono);font-size:.6875rem;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);display:inline-flex;align-items:center;gap:.5rem}
.nav-meta .live{width:6px;height:6px;border-radius:50%;background:var(--good);animation:pulse 2s infinite}
.nav-meta .live.off{background:var(--accent-deep);animation:none}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(111,139,95,.5)}70%{box-shadow:0 0 0 8px rgba(111,139,95,0)}100%{box-shadow:0 0 0 0 rgba(111,139,95,0)}}
#live h1{margin:1.5rem 0 0}#live h1 .line2{font-style:italic;font-weight:400}
.hero-blurb{max-width:36rem;margin-top:1.75rem;font-size:clamp(1rem,1.3vw,1.0625rem);color:var(--ink-soft)}
.live-grid{display:grid;gap:2.5rem;margin-top:3rem}
@media (min-width:768px){.live-grid{grid-template-columns:5fr 7fr;gap:3.5rem;align-items:start}}
.stage-art{position:relative;width:100%;max-width:320px;aspect-ratio:1;margin:1rem 0 2rem}
.stage-art .ring{position:absolute;inset:0;border-radius:50%;border:1px solid var(--rule)}
.stage-art .ring.inner{inset:14%;border-style:dashed;border-color:var(--rule-strong)}
.fan-svg{position:absolute;inset:22%;transform-origin:center}
.fan-svg.spinning{animation:spin var(--spin-speed,1.4s) linear infinite}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
.fan-blade{fill:var(--accent);opacity:.92}.fan-blade.b2{fill:var(--accent-deep)}
.fan-hub{fill:var(--ground);stroke:var(--ink);stroke-width:1.5}.fan-cap{fill:var(--accent)}
.readout{font-family:var(--display);font-weight:300;font-size:clamp(4rem,10vw,6.5rem);line-height:1;letter-spacing:-.03em;display:flex;align-items:baseline;gap:.5rem}
.readout .unit{font-family:var(--mono);font-size:.875rem;letter-spacing:.2em;color:var(--muted);text-transform:uppercase;font-weight:400}
.readout-caption{font-family:var(--display);font-style:italic;font-size:1rem;color:var(--ink-soft);margin-top:.5rem}
.telemetry{display:grid;gap:1.5rem}
.row{padding-top:1.25rem;border-top:1px solid var(--accent)}
.row-head{font-family:var(--mono);font-size:.75rem;letter-spacing:.15em;color:var(--accent-deep);display:flex;justify-content:space-between;align-items:baseline;margin-bottom:.625rem;text-transform:uppercase}
.row-head .label{display:inline-flex;align-items:center;gap:.75rem}
.row-value{font-family:var(--display);font-weight:400;font-size:clamp(1.75rem,3.5vw,2.5rem);line-height:1;margin-bottom:.75rem;letter-spacing:-.02em}
.row-value .small{font-family:var(--mono);font-size:.75rem;letter-spacing:.15em;color:var(--muted);text-transform:uppercase;margin-left:.5rem;font-weight:400}
.row-value em{font-style:italic;color:var(--accent-deep);font-weight:400}
.bar{height:2px;background:var(--rule);position:relative;overflow:hidden}
.bar-fill{height:100%;background:var(--accent);transition:width .4s ease}
.bar-fill.cool{background:var(--cool)}.bar-fill.hot{background:var(--hot)}
.scale{display:flex;justify-content:space-between;font-family:var(--mono);font-size:.625rem;letter-spacing:.15em;color:var(--muted);margin-top:.5rem;text-transform:uppercase}
.meta-strip{display:grid;gap:1.5rem;margin-top:3rem}
@media (min-width:600px){.meta-strip{grid-template-columns:repeat(4,1fr)}}
.meta{border-top:1px solid var(--rule);padding-top:1rem}
.meta .k{font-family:var(--mono);font-size:.625rem;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);margin:0 0 .5rem}
.meta .v{font-family:var(--display);font-size:1.125rem;font-weight:400}
.meta .v em{font-style:italic;color:var(--accent-deep)}
.controls-grid{display:grid;gap:2rem;margin-top:2.5rem}
@media (min-width:768px){.controls-grid{grid-template-columns:3fr 9fr;gap:3.5rem;align-items:start}}
.controls-label p{margin-top:1rem;font-family:var(--display);font-style:italic;font-size:1.0625rem;color:var(--ink-soft);max-width:14rem}
.btn-row{display:flex;flex-wrap:wrap;border-top:1px solid var(--rule)}
.btn{flex:1 1 auto;min-width:80px;padding:1rem .5rem;border-bottom:1px solid var(--rule);border-right:1px solid var(--rule);font-family:var(--display);font-size:1.25rem;font-weight:400;text-align:center;color:var(--ink);transition:all .2s ease;background:transparent}
.btn:last-child{border-right:0}
.btn:hover{color:var(--accent);font-style:italic;background:rgba(201,100,66,.04)}
.btn .pct{font-family:var(--mono);font-size:.625rem;letter-spacing:.2em;color:var(--muted);display:block;margin-top:.25rem;text-transform:uppercase}
.actions{display:flex;flex-wrap:wrap;gap:1.5rem;margin-top:1.5rem}
.action{display:inline-flex;align-items:center;gap:.5rem;font-size:.9375rem;color:var(--accent);border-bottom:1px solid currentColor;padding-bottom:2px;transition:gap .2s ease}
.action:hover{gap:.875rem}
.action.danger{color:var(--hot)}.action.muted{color:var(--ink-soft)}
footer{padding:2.5rem var(--pad-x);max-width:72rem;margin:0 auto;display:flex;flex-direction:column;gap:1rem}
.foot-credit{font-family:var(--display);font-style:italic;font-size:1rem;color:var(--ink-soft)}
.foot-credit .by{color:var(--accent-deep)}
.foot-meta{font-family:var(--mono);font-size:.6875rem;letter-spacing:.15em;text-transform:uppercase;color:var(--muted);margin:0}
@media (min-width:768px){footer{flex-direction:row;align-items:baseline;justify-content:space-between}}
</style>
</head>
<body>
<header class="site-header">
  <div class="container nav">
    <a href="/" class="wordmark" aria-label="Tomlinson Works home">
      <span>Tomlinson</span><span class="dot" aria-hidden="true"></span><span class="suffix">Works</span>
    </a>
    <span class="nav-meta">
      <span class="live __WIFI_LIVE__" aria-hidden="true"></span>
      __WIFI_LABEL__ &middot; refresh 2s
    </span>
  </div>
</header>
<main>
  <section id="live" class="container">
    <p class="eyebrow">Pico Fan &middot; Live Telemetry</p>
    <h1 class="display h1">Thermal control,<br/><span class="line2">crafted in copper.</span></h1>
    <p class="hero-blurb">Closed-loop airflow management for a Raspberry&nbsp;Pi&nbsp;Pico&nbsp;W. Real-time temperature, fan response, and tachometer feedback &mdash; built once, built well.</p>
    <div class="live-grid">
      <div class="stage">
        <p class="eyebrow">01 &middot; Fan</p>
        <div class="stage-art" style="--spin-speed:__SPIN__s">
          <div class="ring"></div>
          <div class="ring inner"></div>
          <svg class="fan-svg __SPIN_CLASS__" viewBox="0 0 100 100" aria-hidden="true">
            <g>
              <path class="fan-blade" d="M50,50 Q60,15 50,5 Q40,15 50,50 Z"/>
              <path class="fan-blade b2" d="M50,50 Q85,40 95,50 Q85,60 50,50 Z"/>
              <path class="fan-blade" d="M50,50 Q40,85 50,95 Q60,85 50,50 Z"/>
              <path class="fan-blade b2" d="M50,50 Q15,60 5,50 Q15,40 50,50 Z"/>
            </g>
            <circle class="fan-hub" cx="50" cy="50" r="10"/>
            <circle class="fan-cap" cx="50" cy="50" r="3"/>
          </svg>
        </div>
        <div class="readout"><span>__SPEED__</span><span class="unit">%</span></div>
        <p class="readout-caption"><em>__SPEED_CAPTION__</em></p>
      </div>
      <div class="telemetry">
        <div class="row">
          <div class="row-head"><span class="label"><span>02</span> &middot; Temperature</span><span>__TEMP_STATUS__</span></div>
          <div class="row-value">__TEMP__<span class="small">&deg; C</span></div>
          <div class="bar"><div class="bar-fill __TEMP_CLASS__" style="width:__TEMP_PCT__%"></div></div>
          <div class="scale"><span>0</span><span>40</span><span>80</span></div>
        </div>
        <div class="row">
          <div class="row-head"><span class="label"><span>03</span> &middot; Fan Speed</span><span>__MODE_LABEL__</span></div>
          <div class="row-value">__SPEED__<span class="small">%</span></div>
          <div class="bar"><div class="bar-fill" style="width:__SPEED__%"></div></div>
          <div class="scale"><span>0</span><span>50</span><span>100</span></div>
        </div>
        <div class="row">
          <div class="row-head"><span class="label"><span>04</span> &middot; Tachometer</span><span>__RPM_STATUS__</span></div>
          <div class="row-value">__RPM__<span class="small">RPM</span></div>
          <div class="bar"><div class="bar-fill cool" style="width:__RPM_PCT__%"></div></div>
          <div class="scale"><span>0</span><span>1500</span><span>3000</span></div>
        </div>
      </div>
    </div>
    <div class="meta-strip">
      <div class="meta"><p class="k">Mode</p><p class="v"><em>__MODE__</em></p></div>
      <div class="meta"><p class="k">Uptime</p><p class="v">__UPTIME__</p></div>
      <div class="meta"><p class="k">WiFi</p><p class="v">__WIFI_STATUS__</p></div>
      <div class="meta"><p class="k">Curve</p><p class="v">30 &middot; 40 &middot; 50 &middot; 60 &middot; 70&deg;</p></div>
    </div>
  </section>
  <section id="override" class="container">
    <div class="controls-grid">
      <div class="controls-label">
        <p class="eyebrow">05 &middot; Override</p>
        <p>Set a fixed duty cycle, or return the fan to the temperature curve.</p>
      </div>
      <div>
        <div class="btn-row">
          <a class="btn" href="/speed?pct=10"><span>10</span><span class="pct">percent</span></a>
          <a class="btn" href="/speed?pct=30"><span>30</span><span class="pct">percent</span></a>
          <a class="btn" href="/speed?pct=50"><span>50</span><span class="pct">percent</span></a>
          <a class="btn" href="/speed?pct=70"><span>70</span><span class="pct">percent</span></a>
          <a class="btn" href="/speed?pct=100"><span>100</span><span class="pct">percent</span></a>
        </div>
        <div class="actions">
          <a class="action" href="/auto">Return to auto <span aria-hidden="true">&rarr;</span></a>
          <a class="action muted" href="/api">JSON API <span aria-hidden="true">&#8599;</span></a>
          <a class="action danger" href="/restart">Restart device <span aria-hidden="true">&#8635;</span></a>
        </div>
      </div>
    </div>
  </section>
</main>
<footer>
  <a href="/" class="wordmark">
    <span>Tomlinson</span><span class="dot" aria-hidden="true"></span><span class="suffix">Works</span>
  </a>
  <p class="foot-credit"><span class="by">Led by Duane Tomlinson,</span> supported by Claude.</p>
  <p class="foot-meta">Pico Fan &middot; New Port Richey, FL &middot; 2026</p>
</footer>
</body>
</html>'''


def build_html_page(controller, temp, speed, rpm, wifi_status):
    temp_pct = min(100, max(0, int((temp / 80.0) * 100)))
    rpm_pct = min(100, max(0, int((rpm / 3000.0) * 100)))
    mode = 'Manual' if controller.manual_override is not None else 'Auto'
    mode_label = 'Manual override' if controller.manual_override is not None else 'Auto curve'

    if speed < 5:
        speed_caption = 'idle'
    elif speed >= 95:
        speed_caption = 'at full duty'
    elif controller.manual_override is not None:
        speed_caption = 'held by override'
    else:
        speed_caption = 'tracking temperature'

    rpm_status = 'Stalled' if rpm < 50 and speed > 10 else ('Healthy' if rpm > 0 else 'Idle')

    if wifi_status['connected']:
        wifi_live = ''
        wifi_label = 'System online'
        wifi_status_text = 'Connected'
    else:
        wifi_live = 'off'
        wifi_label = 'Reconnecting'
        wifi_status_text = wifi_status['status'].title()

    replacements = (
        ('__SPIN__',         _spin_seconds(speed)),
        ('__SPIN_CLASS__',   'spinning' if speed >= 5 else ''),
        ('__SPEED_CAPTION__', speed_caption),
        ('__SPEED__',        str(speed)),
        ('__TEMP_STATUS__',  get_temp_status(temp)),
        ('__TEMP_CLASS__',   _temp_class(temp)),
        ('__TEMP_PCT__',     str(temp_pct)),
        ('__TEMP__',         '{:.1f}'.format(temp)),
        ('__MODE_LABEL__',   mode_label),
        ('__RPM_STATUS__',   rpm_status),
        ('__RPM_PCT__',      str(rpm_pct)),
        ('__RPM__',          _format_thousands(rpm)),
        ('__MODE__',         mode),
        ('__UPTIME__',       controller.get_uptime()),
        ('__WIFI_LIVE__',    wifi_live),
        ('__WIFI_LABEL__',   wifi_label),
        ('__WIFI_STATUS__',  wifi_status_text),
    )
    html = HTML_TEMPLATE
    for placeholder, value in replacements:
        html = html.replace(placeholder, value)
    return html


# ============ WEB SERVER ============
def send_response(conn, body, content_type='application/json', status='200 OK'):
    body_bytes = body.encode('utf-8')
    response = 'HTTP/1.1 {}\r\n'.format(status)
    response += 'Content-Type: {}; charset=utf-8\r\n'.format(content_type)
    response += 'Content-Length: {}\r\n'.format(len(body_bytes))
    response += 'Connection: close\r\n\r\n'
    conn.sendall(response.encode('utf-8'))
    conn.sendall(body_bytes)


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

