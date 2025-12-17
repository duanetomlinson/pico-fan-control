```

## What's New

| Feature | How It Works |
|---------|--------------|
| **Watchdog Timer** | Resets Pico if code hangs for >8 seconds |
| **WiFi Manager** | Checks connection every 30s, auto-reconnects |
| **Fan Always Runs** | Fan control loop is independent of WiFi/web |
| **Server Recovery** | Recreates socket if WiFi reconnects |
| **Error Counting** | Resets after too many consecutive errors |
| **`/restart` Endpoint** | Manual restart from web UI |
| **Status Logging** | Prints status every 60 seconds |

## Priority Order
```
1. Watchdog feed     <- Always runs first
2. Fan control       <- CRITICAL, never stops
3. WiFi check        <- Reconnects if needed
4. Web server        <- Only if WiFi is up
```

## New Dashboard Info
```
| WIFI:   OK (CONNECTED)             |
```

or
```
| WIFI:   RECONN (CONNECTING)        |