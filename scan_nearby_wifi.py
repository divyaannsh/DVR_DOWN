#!/usr/bin/env python3
import objc
import sys

try:
    objc.loadBundle('CoreWLAN', bundle_path='/System/Library/Frameworks/CoreWLAN.framework', module_globals=globals())
    COREWLAN_OK = True
except Exception as e:
    COREWLAN_OK = False
    print(f"Error loading CoreWLAN: {e}")

def scan_wifi():
    if not COREWLAN_OK:
        print("CoreWLAN framework could not be loaded.")
        return

    try:
        # Get default Wi-Fi client and interface (e.g. en0)
        client = CWWiFiClient.sharedWiFiClient()
        interface = client.interface()
        
        print(f"Scanning via interface: {interface.interfaceName()}...")
        
        # Trigger scan
        networks, error = interface.scanForNetworksWithSSID_error_(None, None)
        
        if error:
            print(f"Scan failed with error: {error}")
            return

        results = []
        seen = set()
        
        for network in networks:
            ssid = network.ssid()
            bssid = network.bssid()
            rssi = network.rssiValue()
            
            # Safe parsing
            try:
                channel = network.wlanChannel().channelNumber()
            except Exception:
                channel = 0
                
            ssid_str = str(ssid) if ssid else "<Hidden>"
            bssid_str = str(bssid) if bssid else "N/A"
            rssi_val = rssi if rssi is not None else -99
            chan_val = channel if channel is not None else 0

            # Filter duplicates to keep clean list
            if (ssid_str, bssid_str) not in seen:
                seen.add((ssid_str, bssid_str))
                # Identify suspicious/unknown patterns
                ssid_lower = ssid_str.lower()
                status = "Unknown / Suspicious" if (ssid_str == "<Hidden>" or "camera" in ssid_lower or "cam" in ssid_lower or "ipc" in ssid_lower or ssid_str.startswith("ESP_") or len(ssid_str) == 12) else "Normal AP"
                results.append([ssid_str, bssid_str, f"{rssi_val} dBm", f"Ch {chan_val}", status, rssi_val])

        # Sort by signal strength (stronger signal/closer device first)
        results.sort(key=lambda x: x[5], reverse=True)

        print("\n" + "="*95)
        print(f"📡 Nearby WiFi Networks Scan (Total: {len(results)})")
        print("Sorted by proximity (Strongest signal / closest device first)")
        print("="*95)
        
        headers = ["SSID (WiFi Name)", "BSSID (MAC)", "Signal Strength (RSSI)", "Channel", "Type Assessment"]
        print(f"{headers[0]:<25} {headers[1]:<20} {headers[2]:<25} {headers[3]:<10} {headers[4]}")
        print("-" * 95)
        for row in results:
            # Highlight suspicious items in yellow
            color_prefix = "\033[93m" if "Suspicious" in row[4] else ""
            color_suffix = "\033[0m" if color_prefix else ""
            print(f"{color_prefix}{row[0]:<25} {row[1]:<20} {row[2]:<25} {row[3]:<10} {row[4]}{color_suffix}")
        print("="*95 + "\n")
        
        print("💡 Suspicious Type Rules:")
        print("  - 'ESP_...' or similar: Generic smart chips often used in DIY/spy cameras.")
        print("  - 'IPC...' or 'cam...': Standard IP camera default hotspot names.")
        print("  - <Hidden>: Networks that do not broadcast SSID (can be cameras or hidden routers).")

    except Exception as e:
        print(f"An error occurred during scan: {e}")
        print("Make sure Terminal / Python has Location Services / Network permission enabled in Mac settings.")

if __name__ == "__main__":
    scan_wifi()
