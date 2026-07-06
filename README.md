# SAKURA KAKUMEI Asset and Media Extraction Tool

《樱花革命（サクラ革命）》手游数据包解密工具脚本汇总仓库

# 使用方法 / Usage

## 文件位置 / Files

| 文件 / File | 用途 / Purpose |
|---|---|
| `sakura_asset_cipher.bat` | 资产缓存解密/加密入口 / Asset cache decrypt/encrypt entry point |
| `sakura_asset_cipher.py` | 资产缓存处理脚本 / Asset cache processing script |
| `cpk_unpack.bat` | CPK 批量解包入口 / CPK batch unpack entry point |
| `cpk_unpack.py` | 纯 Python CPK 解包脚本 / Pure Python CPK unpacker |
| `media_convert.bat` | 双击或拖拽使用的入口 / Double-click or drag-and-drop entry point |
| `media_convert.py` | 主转换脚本 / Main conversion script |

**请下载并确定您可以在系统变量中正常调用 `ffmpeg.exe`和`vgmstream-cli.exe` 。**  

**You need to download and configure that `ffmpeg.exe` and `vgmstream-cli.exe` is available in system PATH.**  



## 资产缓存解密 / Asset Cache Decrypt

脚本入口：

```bat
sakura_asset_cipher.bat
```

Script entry point:

```bat
sakura_asset_cipher.bat
```

预览单个 `_d` 文件是否可解密：

```powershell
.\sakura_asset_cipher.bat --preview "\path\to\file_d"
```

Preview whether a single `_d` file can be decrypted:

```powershell
.\sakura_asset_cipher.bat --preview "\path\to\file_d"
```

解密单个 `_d` 文件：

```powershell
.\sakura_asset_cipher.bat "\path\to\file_d" "\path\to\output.unityfs"
```

Decrypt a single `_d` fil

```powershell
.\sakura_asset_cipher.bat "\path\to\file_d" "\path\to\output.unityfs"
```

批量处理 AssetCache 目录：

```powershell
.\sakura_asset_cipher.bat --batch "\path\to\AssetCache" "\decrypted_asset"
```

Batch process an AssetCache folder:

```powershell
.\sakura_asset_cipher.bat --batch "\path\to\AssetCache" "\decrypted_asset"
```

使用 Addressables `catalog.json` 恢复较可读的文件名：

```powershell
.\sakura_asset_cipher.bat --batch "\path\to\AssetCache" "\decrypted_asset" --catalog "\path\to\catalog.json"
```

Use Addressables `catalog.json` to restore more readable file names:

```powershell
.\sakura_asset_cipher.bat --batch "\path\to\AssetCache" "\decrypted_asset" --catalog "\path\to\catalog.json"
```

计算 URL 对应的 AssetCache 文件名：

```powershell
.\sakura_asset_cipher.bat --cache-name "/path/file.bundle"
```

Print the AssetCache file name for a URL:

```powershell
.\sakura_asset_cipher.bat --cache-name "/path/file.bundle"
```

常用批量选项：

| 选项 / Option | 用途 / Purpose |
|---|---|
| `--copy-plaintext` | 批量时复制已经是明文的 UnityFS/CPK 文件 / Copy plaintext UnityFS/CPK files in batch mode |
| `--keep-suffix` | 保留原始 `_d` 输出文件名 / Keep original `_d` output names |
| `--limit N` | 只处理前 N 个文件 / Process only the first N files |
| `--no-progress` | 关闭实时进度条 / Disable live progress |



## CPK 解包 / Unpack CPK

脚本入口：

```bat
cpk_unpack.bat
```

Script entry point:

```bat
cpk_unpack.bat
```

双击后选择 CPK 文件或包含 CPK 的文件夹。

Double-click it to choose CPK files or a folder containing CPK files.

处理默认目录 `decrypted_asset`：

```powershell
.\cpk_unpack.bat --no-gui
```

Process the default `decrypted_asset` folder:

```powershell
.\cpk_unpack.bat --no-gui
```

处理指定 CPK 文件或目录：

```powershell
.\cpk_unpack.bat "\decrypted_asset\sample.cpk"
.\cpk_unpack.bat "\decrypted_asset"
```

Process a specific CPK file or folder:

```powershell
.\cpk_unpack.bat "\decrypted_asset\sample.cpk"
.\cpk_unpack.bat "\decrypted_asset"
```

指定输出目录：

```powershell
.\cpk_unpack.bat --no-gui -o "\cpk_unpacked"
```

Set output folder:

```powershell
.\cpk_unpack.bat --no-gui -o "\cpk_unpacked"
```

只测试前 N 个 CPK：

```powershell
.\cpk_unpack.bat --no-gui --limit 5 -o "\cpk_unpacked_test"
```

Test only the first N CPK files:

```powershell
.\cpk_unpack.bat --no-gui --limit 5 -o "\cpk_unpacked_test"
```

覆盖已有解包文件：

```powershell
.\cpk_unpack.bat --no-gui --overwrite
```

Overwrite existing extracted files:

```powershell
.\cpk_unpack.bat --no-gui --overwrite
```

输出格式：

```text
<输出目录>\<CPK文件名>.unpack\...
```

Output layout:

```text
<output folder>\<CPK file name>.unpack\...
```



## 转换CPK中提取的AWB、USM媒体 / Convert Media (.awb and .usm) extracted from CPK 

### 方式 1：双击 / Option 1: Double-click

双击：

```bat
media_convert.bat
```

会弹出选择窗口。可以选择一个文件夹递归处理，也可以选择单个或多个文件。

Double-click:

```bat
media_convert.bat
```

A file picker opens. You can choose a folder recursively or select one or more files.

### 方式 2：拖拽 / Option 2: Drag and drop

把 `.acb`、`.awb`、`.usm` 文件或包含这些文件的文件夹拖到：

```bat
media_convert.bat
```

Drag `.acb`, `.awb`, `.usm` files, or folders containing them, onto:

```bat
media_convert.bat
```

### 方式 3：命令行 / Option 3: Command line

处理默认目录 `decrypted_asset`：

```powershell
.\media_convert.bat --no-gui
```

Process the default `decrypted_asset` folder:

```powershell
.\media_convert.bat --no-gui
```

处理指定文件或文件夹：

```powershell
.\media_convert.bat "\decrypted_asset"
.\media_convert.bat "\decrypted_asset\sample.unpack\movie.usm"
```

Process a specific file or folder:

```powershell
.\media_convert.bat "\decrypted_asset"
.\media_convert.bat "\decrypted_asset\sample.unpack\movie.usm"
```

指定输出目录：

```powershell
.\media_convert.bat --no-gui -o "\converted_media"
```

Set output folder:

```powershell
.\media_convert.bat --no-gui -o "\converted_media"
```



## Sakura Kakumei USM Key

默认 USM key 是：

```text
382759
```

通常不需要手动填写。需要覆盖时：

```powershell
.\media_convert.bat --usm-key 382759 "\decrypted_asset"
```

The default USM key is:

```text
382759
```

Usually you do not need to set it manually. To override it:

```powershell
.\media_convert.bat --usm-key 382759 "\decrypted_asset"
```

禁用 USM 解密：

```powershell
.\media_convert.bat --usm-key "" "\decrypted_asset"
```

Disable USM decryption:

```powershell
.\media_convert.bat --usm-key "" "\decrypted_asset"
```



## 输出 / Output

默认输出目录：

```text
converted_media
```

Default output folder:

```text
converted_media
```

转换结果：

| 输入 / Input | 输出 / Output |
|---|---|
| `.acb`, `.awb` | `.wav` |
| `.usm` | `.mp4` |

日志目录：

```text
converted_media\_logs
```

Log folder:

```text
converted_media\_logs
```

失败列表：

```text
converted_media\_failed.txt
```

Failed file list:

```text
converted_media\_failed.txt
```



## 致谢（Thanks to these repositories!）

- https://github.com/vgmstream/vgmstream for Cri Keys
- https://github.com/Hengle/cripaktools2 for CPK extraction
- https://github.com/ToaHartor/GI-cutscenes for usm decryption ideas
