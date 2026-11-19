#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Voice-controlled remote PC power for Bemfa Cloud (MQTT).

Payload contract:
    "on"  -> send a Wake-on-LAN magic packet, then report "01"
    "off" -> graceful Windows shutdown over SSH, then report "00"

Run as root (etherwake needs raw sockets; ssh uses /root/.ssh/id_rsa).
"""

import subprocess
import time

import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# >>> 改成你自己的值 / REPLACE WITH YOUR OWN VALUES
# ---------------------------------------------------------------------------
BEMFA_UID = "YOUR_BEMFA_UID"        # 巴法云私钥（控制台可查）
TOPIC = "pcpower001"                # 开关主题名，与米家/小爱绑定的一致

BRIDGE_IFACE = "eth0"               # 跳板机上网卡的名称，用 `ip -br addr` 查
TARGET_MAC = "AA:BB:CC:DD:EE:FF"    # 目标 PC 有线网卡的 MAC
TARGET_HOST = "192.168.1.10"        # 目标 PC 的固定局域网 IP
TARGET_USER = "YourUser"            # 目标 PC 的 Windows 账户名（管理员组）
# ---------------------------------------------------------------------------


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to Bemfa Cloud", flush=True)
        client.subscribe(TOPIC)
        client.publish(TOPIC, "00")


def on_message(client, userdata, msg):
    payload = msg.payload.decode(errors="ignore").strip()
    print(f"Received command: {payload}", flush=True)

    if payload == "on":
        try:
            subprocess.run(
                ["etherwake", "-i", BRIDGE_IFACE, TARGET_MAC],
                check=True,
                timeout=10,
            )
            time.sleep(3)
            client.publish(TOPIC, "01")
        except Exception as exc:  # noqa: BLE001
            print(f"WOL failed: {exc}", flush=True)

    elif payload == "off":
        try:
            subprocess.run(
                ["ssh", f"{TARGET_USER}@{TARGET_HOST}", "shutdown /s /t 0"],
                check=True,
                timeout=30,
            )
            client.publish(TOPIC, "00")
        except Exception as exc:  # noqa: BLE001
            print(f"SSH shutdown failed: {exc}", flush=True)


def main():
    client = mqtt.Client(client_id=BEMFA_UID)
    client.on_connect = on_connect
    client.on_message = on_message

    print("Starting WOL Listener...", flush=True)
    client.connect("bemfa.com", 9501, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()
