# 语音远程开关电脑 · Voice-Controlled Remote PC Power

> 不用插线板、不用开机卡、不依赖智能插座硬件，仅靠一台常开的局域网小主机（Debian / 树莓派 / NAS 均可）作为"跳板"，实现「小爱同学说一句话 → 开机 / 关机」。
>
> A hardware-free way to power your PC on/off by voice: an always-on LAN box (Debian / Raspberry Pi / NAS) acts as the bridge between Mijia (Xiaoai voice) and your Windows PC — using **Wake-on-LAN** to boot it and **SSH** to shut it down.

---

## ⚠️ 风险提示（务必先读）/ Read the risks first

这套方案的本质是：**在局域网里放一台常开主机，它持有一把能免密登入你 Windows 的私钥，并对外暴露一个能被云端消息触发的入口。** 它很好用，但你要清楚自己在承担什么。

The core idea is: *an always-on LAN host holds a private key that can log into your Windows machine without a password, and exposes an entry point that can be triggered by a cloud message.* Convenient — but know what you are trading off.

| 风险 | 说明 | 缓解措施 |
|---|---|---|
| **私钥即钥匙** | 跳板机上的私钥一旦泄露，攻击者可直接免密登入目标 PC，等同把家门钥匙放在门口 | 私钥仅存于跳板机，权限 600；不要在仓库、网盘、聊天记录里出现明文 |
| **云端开关可被误触发** | 巴法云账号被盗/被家人误操作，都可能在你正在用电脑时触发关机 | 账号开两步验证；给开关改名并限制家人可见范围；关机前可加一次确认 |
| **云端依赖** | 巴法云 / 米家 / 小爱任一环节故障，链路即失效 | 保留物理电源键作为兜底；不要把它当成唯一开关手段 |
| **关机是硬中断** | 语音关机等于执行 `shutdown`，未保存的文档会丢 | 关机前先自行保存；或改用"先提醒再关机"的两段式流程 |
| **内网端口暴露** | 为了免密登入，目标 PC 要开 22 端口 | 只在局域网开放；路由器上**绝不要**做 22 端口映射到公网 |
| **唤醒依赖硬件** | 网卡驱动、BIOS 的 ErP 设置、快速启动都会让魔术包失效 | 见下文"Windows 侧"一节的验收命令，装完必须逐条验证 |
| **常开主机成为单点** | 跳板机一挂，开关机全部失效 | 用低功耗设备、开自动重启、定期检查服务状态 |

> 如果你打算把这套东西放到公网（比如从公司关机），请**不要**直接暴露 SSH。改用 WireGuard / Tailscale 之类的隧道，并限制来源。
>
> If you plan to reach this from outside your LAN, do **not** expose SSH directly. Put it behind WireGuard / Tailscale and restrict sources.

---

## 一、原理 / How it works

```
  Xiaoai (voice)  →  Mijia App  →  Bemfa Cloud (MQTT topic)
                                        │   payload: "on" / "off"
                                        ▼
                        Bridge host (Debian / Pi / NAS, always on)
                        service: wol-listener
                                        │
                    ┌───────────────────┴────────────────────┐
                    │ "on"                                   │ "off"
                    ▼                                        ▼
        etherwake -i <IFACE> <MAC>                 ssh <USER>@<PC_IP> "shutdown /s /t 0"
        (magic packet, wakes PC from S5)           (graceful shutdown)
                    │                                        │
                    └────────────► Windows PC ◄──────────────┘
```

关键点 / Key points：

1. **开机**靠魔术包（Wake-on-LAN），是网卡硬件能力，不需要任何插座类硬件。
   *Boot* uses a magic packet — a NIC hardware feature, no smart plug needed.
2. **关机**靠 SSH 执行系统关机命令，属于"软件关机"，比断电更安全。
   *Shutdown* is a software shutdown over SSH — safer than cutting power.
3. 云端只负责"传一句话"，真正的动作都在你自己的局域网里完成，**不依赖厂商的开关硬件**。
   The cloud only carries the command; the actual action happens inside your own LAN.

---

## 二、前置条件 / Prerequisites

| 项 | 要求 |
|---|---|
| 目标 PC | 有线网卡（推荐千兆板载）、支持 WOL、BIOS 有 `Power On By PCI-E` |
| 跳板机 | 常开的 Linux（本文以 Debian 12 为例），与目标 PC 在同一局域网 |
| 云端 | 巴法云账号 + 米家 App + 小爱音箱 |
| 网络 | 目标 PC 建议固定 IP（DHCP 保留或静态） |

---

## 三、Step 1：云端开关 / Create the cloud switch

1. 注册 [巴法云](https://cloud.bemfa.com/)，创建一个**开关主题**，例如 `pcpower001`（下文记作 `<TOPIC>`）。
2. 在米家 App 中添加该巴法云设备，命名为"电脑"之类。
3. 在小爱训练/智能场景里配置语音指令：说「开电脑」→ 开关置 `on`；说「关电脑」→ 开关置 `off`。
4. 约定载荷：`on` = 开机，`off` = 关机；脚本执行成功后会回写 `01` / `00` 让 App 状态同步。

> 注意：巴法云的主题名是公开信道名，**不要**用 `你的名字+电脑` 这类可猜的名字。

---

## 四、Step 2：跳板机与监听服务 / Bridge host & listener

### 2.1 依赖 / Dependencies

```bash
sudo apt update
sudo apt install -y python3-pip etherwake
pip3 install paho-mqtt
```

- `etherwake`：发送魔术包（需要 root/raw socket 权限）
- `paho-mqtt`：连接巴法云 MQTT

### 2.2 脚本 / The listener script

见仓库内 [`examples/wol_listener.py`](examples/wol_listener.py)，把占位符换成你自己的值：

```python
BRIDGE_IFACE = "eth0"          # 跳板机连接局域网的网卡名，用 ip -br addr 查
TARGET_MAC   = "AA:BB:CC:DD:EE:FF"
TARGET_HOST  = "192.168.1.10"  # 目标 PC 的固定 IP
TARGET_USER  = "YourUser"      # 目标 PC 的 Windows 账户名
TOPIC        = "pcpower001"
```

> **最容易踩的坑**：跳板机的网卡名写错（例如写成 `eth0` 但实际是 `ens192`），`etherwake` 会直接报 `Device does not exist`，表现就是"开电脑没反应"。上线前先 `ip -br addr` 核对。

### 2.3 systemd 单元 / Systemd unit

见 [`examples/wol-listener.service`](examples/wol-listener.service)：

```bash
sudo cp examples/wol-listener.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wol-listener
sudo systemctl status wol-listener
journalctl -u wol-listener -n 30 --no-pager
```

> 以 root 运行的理由：`etherwake` 需要原始套接字权限；SSH 免密登录使用 root 的 `~/.ssh/id_rsa`。若你不想用 root，可改为给 `etherwake` 单独提权 + 用普通用户的密钥，但复杂度更高。

---

## 五、Step 3：Windows 侧开启 WOL / Enable Wake-on-LAN on Windows

> 这一节是整套方案里最容易失败的部分，**请逐条验证**。
> This is the most failure-prone part — verify every item.

### 3.1 网卡驱动（决定 WOL 能否开启）

Windows 自带的通用 Realtek 驱动常常把 `WakeOnMagicPacket` 报告为 `Unsupported`，此时任何设置都不生效。**必须换成厂商/Windows Update 提供的官方驱动。**

```powershell
# 验收：WakeOnMagicPacket 必须是 Enabled，不能是 Unsupported
Get-NetAdapterPowerManagement -Name '<网卡名>' |
  Select-Object AllowComputerToTurnOffDevice,WakeOnMagicPacket,WakeOnPattern
```

### 3.2 打开唤醒项、关掉深度省电

```powershell
$nic = '<网卡名>'
Set-NetAdapterAdvancedProperty -Name $nic -RegistryKeyword '*WakeOnMagicPacket'  -RegistryValue 1
Set-NetAdapterAdvancedProperty -Name $nic -RegistryKeyword '*WakeOnPattern'      -RegistryValue 1
Set-NetAdapterAdvancedProperty -Name $nic -RegistryKeyword 'S5WakeOnLan'         -RegistryValue 1
Set-NetAdapterAdvancedProperty -Name $nic -RegistryKeyword 'EEE'                 -RegistryValue 0
Set-NetAdapterAdvancedProperty -Name $nic -RegistryKeyword 'AdvancedEEE'         -RegistryValue 0
Set-NetAdapterAdvancedProperty -Name $nic -RegistryKeyword 'EnableGreenEthernet' -RegistryValue 0
Set-NetAdapterAdvancedProperty -Name $nic -RegistryKeyword 'GigaLite'            -RegistryValue 0

# 关键：把网卡登记为"可唤醒设备"，不做这步魔术包无效
powercfg /deviceenablewake '<网卡的设备描述>'

# 验收：输出里必须出现这块网卡
powercfg /devicequery wake_armed
```

> 不同厂商的关键字不完全一样（Realtek 常见 `S5WakeOnLan`，Intel 常见 `*WakeOnMagicPacket` + `WakeOnLink`）。以 `Get-NetAdapterAdvancedProperty -AllProperties` 里实际存在的项为准。

### 3.3 关闭快速启动（重要）

Windows 里点"关机"默认是**混合关机**，网卡不工作，魔术包打不醒。

```powershell
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' `
  -Name HiberbootEnabled -Value 0 -Type DWord
```

验收：`powercfg /a` 中"快速启动"应显示为不可用（策略禁用）。
代价：冷启动比原来慢几秒。

### 3.4 BIOS

进入固件设置（常见位置 `Advanced → APM Configuration`）：

- `ErP Ready` = **Disabled**（启用 ErP 会在 S5 断电，魔术包必失败）
- `Power On By PCI-E` / `Wake On LAN` = **Enabled**

### 3.5 装 OpenSSH 服务端（供跳板机关机用）

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service sshd -StartupType Automatic
Start-Service sshd
New-NetFirewallRule -DisplayName 'OpenSSH-Server-In-TCP' -Direction Inbound `
  -Protocol TCP -LocalPort 22 -Action Allow -Profile Private
```

> 建议 `-Profile Private` 或者限定 `-RemoteAddress 192.168.1.0/24`，只允许内网访问。

### 3.6 授权跳板机的公钥

Windows OpenSSH 有一个坑：**管理员组用户**的授权文件不是 `~/.ssh/authorized_keys`，而是
`C:\ProgramData\ssh\administrators_authorized_keys`，且权限必须只保留 `Administrators` 和 `SYSTEM`。

```powershell
# 从跳板机把公钥推过来（在跳板机上执行，需输一次 Windows 密码）
# scp ~/.ssh/id_rsa.pub <TARGET_USER>@<TARGET_HOST>:C:/Users/<TARGET_USER>/pub.key

$key = (Get-Content "C:\Users\<TARGET_USER>\pub.key" -Raw).Trim()
[IO.File]::WriteAllText('C:\ProgramData\ssh\administrators_authorized_keys',
  $key + "`n", (New-Object Text.UTF8Encoding($false)))

icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r `
  /grant "Administrators:F" /grant "SYSTEM:F"

Restart-Service sshd
Remove-Item "C:\Users\<TARGET_USER>\pub.key" -Force
```

验收（在跳板机上）：

```bash
ssh -o PasswordAuthentication=no <TARGET_USER>@<TARGET_HOST> hostname
```

能直接返回主机名且不问密码，即成功。

---

## 六、第一次联调 / First end-to-end test

| 步骤 | 现象 |
|---|---|
| 1. 手动触发主题为 `on`（在巴法云网页或 App 上拨开关） | `journalctl -u wol-listener` 出现 `Received command: on`，PC 从关机态启动 |
| 2. 手动触发 `off` | 日志出现 `Received command: off`，PC 正常软关机 |
| 3. 用小爱说「开电脑」 | 同上，开关状态回写 `01` |
| 4. 用小爱说「关电脑」 | 同上，开关状态回写 `00` |

> ⚠️ 联调阶段请先保存好所有文档再测关机。

---

## 七、常见故障对照表 / Troubleshooting

| 现象 | 最可能原因 | 怎么查 |
|---|---|---|
| 说"开电脑"没反应 | 网卡驱动不支持 WOL | `Get-NetAdapterPowerManagement` 看 `WakeOnMagicPacket` 是否 `Unsupported` |
| 同上 | 快速启动没关 | `powercfg /a` 里"快速启动"是否可用 |
| 同上 | 网卡未登记为唤醒设备 | `powercfg /devicequery wake_armed` 是否包含网卡 |
| 同上 | BIOS ErP 开着 | 进 BIOS 看 `ErP Ready` |
| 同上 | 跳板机网卡名写错 | `ip link show <IFACE>` 是否 `does not exist` |
| 同上 | 魔术包没发出去 | 跳板机上手动 `etherwake -i <IFACE> <MAC>` 看报错 |
| 说"关电脑"没反应 | 主机密钥变了（重装系统后） | 跳板机手动 `ssh <USER>@<IP> hostname` 是否报 `Host key verification failed` |
| 同上 | 公钥放错位置/权限不对 | 必须是 `administrators_authorized_keys` + 仅 Admins/SYSTEM |
| 同上 | sshd 没跑 | 目标机 `Get-Service sshd` |
| 同上 | 防火墙/安全软件拦截 | 22 端口入站规则；第三方安全软件单独放行 |
| 开关状态不刷新 | MQTT 未连上 | `journalctl -u wol-listener` 里是否有 `Connected to` |

---

## 八、安全加固清单 / Hardening checklist

- [ ] 目标 PC 的 22 端口**只在内网**开放，路由器上不做公网映射
- [ ] 跳板机私钥权限 `600`，并且有加密备份（密码管理器 / 加密压缩包）
- [ ] 巴法云、米家账号均开启两步验证
- [ ] 跳板机 SSH 本身禁用密码登录，只留密钥
- [ ] 关机命令可加白名单：在跳板机侧只允许固定的 `shutdown /s /t 0`，不接受任意命令
- [ ] 需要从外网控制时，用 WireGuard / Tailscale 隧道，不暴露端口
- [ ] 定期 `systemctl status wol-listener` 与 `journalctl` 巡检
- [ ] 保留物理电源键，避免云端失效后无法开机

---

## 九、许可 / License

MIT。欢迎 issue / PR 补充不同网卡与 BIOS 的差异细节。

---

## 十、免责声明 / Disclaimer

本方案涉及远程关机与免密登录，请仅在**你自己的设备与网络**上使用。因误操作、密钥泄露、配置不当导致的数据丢失或安全问题，由使用者自行承担。作者不对任何由此产生的损失负责。

This project involves remote shutdown and passwordless login. Use it only on devices and networks you own. You are responsible for any data loss or security incident caused by misconfiguration or key leakage.
