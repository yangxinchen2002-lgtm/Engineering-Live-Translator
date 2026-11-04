# ELT/1 本地命名管道协议

仅用于本机 Windows x64。C++ helper 创建 `\\.\pipe\ELT-<32位随机hex>` 双向 byte-mode 管道，Python 连接。拒绝远程客户端，DACL 只允许当前 Windows 用户，句柄不继承，启用 FIRST_PIPE_INSTANCE。随机名称避免碰撞，不提供对同一用户恶意程序的安全隔离。

每条消息为 `uint32 body_length` + 固定 **52 字节**头 + payload。全部整数、PCM 为**小端**，无隐式填充，长度不含前缀；body 允许 52…1048576 字节，先校验长度再分配。短读/粘包由 exact-read 处理。版本 1 不做兼容猜测，未知版本、保留字段、类型或格式立即失败。

| 头偏移 | 字段 | 类型/含义 |
|---|---|---|
| 0 | version | u16，1 |
| 2 | kind | u16，AUDIO=1 START=2 STOP=3 STATUS=4 ERROR=5 |
| 4 | sequence | u64，每个方向从 0 开始，每条消息加 1 |
| 12 | sample_rate | u32，原生捕获流 Hz |
| 16 | channels | u16 |
| 18 | sample_format | u16，NONE=0 S16=1 packed-S24=2 S32=3 F32=4 |
| 20 | sample_count | u32，每声道采样帧数（不是交错样本总数） |
| 24 | capture_timestamp | u64，GetBuffer 返回的 QPC，单位 100 ns |
| 32 | first_sample | u64，本会话累计捕获采样帧位置 |
| 40 | flags | u32，原始 AUDCLNT_BUFFERFLAGS |
| 44 | valid_bits | u16，有效位数，整数按 Windows 定义左对齐 |
| 46 | reserved | u16，必须为 0 |
| 48 | channel_mask | u32，WAVEFORMATEXTENSIBLE 通道掩码，未知为 0 |

AUDIO payload 为交错 PCM，精确长度 `frames * channels * container_bytes`。静音包无论原生 Data 是否为空，都传输显式零数据。浮点不允许 NaN/Inf。序号间隙、重复、first_sample 间隙、运行中的 discontinuity、时间戳错误/倒退均视为不完整并终止。首包的 discontinuity 仅表示流起点，保留并记录其标记，不计为已丢失历史音频。

控制消息的采样相关字段必须全 0，payload 为 UTF-8 JSON object。Python → helper 的 START、STOP、STATUS 使用精确 `{}`（v1 的最小控制参数）。PID、创建时间和管道名通过 helper 命令行提供，并在 Start 时重新核验。helper → Python 的 STATUS/ERROR 可携带额外 JSON 字段。

顺序：连接 → START(seq0) → STATUS(started，signal=unverified) → AUDIO/每秒 STATUS → STOP → 排空队列 → STATUS(stopped) → helper 退出。Start 只接受一次；重复 START 或无效控制报错。STATUS 请求由下一次捕获心跳回应，通常不超过 1.25 秒。没有音频包时仍发心跳；它不表示存在可听声音。

异常可发 ERROR 后退出；管道已断开/输出队列已满时 ERROR 未必能送达，此时必须以 helper stderr + 非零退出码诊断，Python 不得当作成功。stderr 永不混入二进制流。标准输出留空。

`transport_fault`：1=控制读取失败/客户端断开，2=输出失败或写超时，3=有界队列溢出。输出线程在 stderr 单独报告具体操作/HRESULT/超时信息。

捕获线程与管道写线程之间为 SPSC 有界队列：最多 256 包及 4 MiB payload，超限即明确停止；绝不默默丢帧后继续。控制读在独立线程，STOP 不等待写线程。读写采用可取消 overlapped I/O；连接与激活各 10 秒上限，单次写 2 秒，Python 单次接收 3 秒。异常时父进程有界等待、终止并回收 helper。

采样时间轴只累计 API 实际交付的数据；暂停无包期间不合成音频。QPC 保留真实时间间隔，不能把累计采样时长当作墙钟时长。重采样输出从 sample 0 起；因果 FIR 具有可查询固定群延迟（常见转换为 10 个 16 kHz 样本），保留启动瞬态，不自动补零尾部。结束时最后一帧允许短于 320 个样本并显式交付。

