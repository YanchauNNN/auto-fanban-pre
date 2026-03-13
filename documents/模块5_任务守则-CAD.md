# 妯″潡5_浠诲姟瀹堝垯-CAD锛堝綋鍓嶆満鍣ㄥ疄閰嶇暀妗ｇ増锛?
> 閫傜敤鑼冨洿锛歚E:\project\auto-fanban-pre` 浠撳簱锛屾ā鍧?锛圕AD-DXF 鎵ц閾捐矾锛?> 
> 鐩爣锛氳鍚庣画 AI 缁存姢鑰呭湪涓嶄緷璧栦笂涓嬫枃璁板繂鐨勬儏鍐典笅锛屾寜鏈枃鍗冲彲瀹氫綅璺緞銆佹墽琛屼换鍔°€佹帓鏌ラ棶棰樸€?> 
> 鏇存柊鏃堕棿锛歚2026-03-04`

---

## 0) 鍐崇瓥涓庤竟鐣岋紙蹇呴』閬靛畧锛?
- 涓婚摼璺浐瀹氾細`.NET + AutoCAD Core Console`銆?- 涓嶅厑璁糕€滃帇閿?鍚為敊鈥濓細鍑虹幇鎶ラ敊蹇呴』璁板綍鏍瑰洜锛屼笉鍋氶潤榛樺拷鐣ャ€?- 鎵撳嵃閾捐矾瑙勫垯锛?  - 鍏堟寜鍚嶇О鍖归厤 PC3 绾稿紶銆?  - 鎵撳嵃绐楀彛鏉ヨ嚜 DXF 璇嗗埆鍥炬椤剁偣锛圵CS锛夛紝鎵撳嵃浣跨敤 Window 妯″紡銆?  - `center_plot=false`锛宍plot_offset=(0,0)`锛宍margins_mm=0`銆?  - 姣斾緥涓?`manual_integer_from_geometry`锛屽苟鎵ц鏁存暟鍖栬鍒欍€?- 寮曟搸绛栫暐锛氫紭鍏?.NET锛涘彧鏈?.NET 澶辫触鏃舵墠鍏佽鍥為€€ LISP锛堢敱閰嶇疆鎺у埗锛夈€?
---

## 1) 褰撳墠鏈哄櫒鐪熷疄璺緞锛堢粷瀵硅矾寰勶紝閫愰」鏍稿锛?
## 1.1 浠撳簱涓庤繍琛岀幆澧?
- 浠撳簱鏍圭洰褰曪細`E:\project\auto-fanban-pre`
- 鍚庣鐩綍锛歚E:\project\auto-fanban-pre\backend`
- Python 铏氭嫙鐜锛歚E:\project\auto-fanban-pre\backend\.venv`
- 甯哥敤瑙ｉ噴鍣細`E:\project\auto-fanban-pre\backend\.venv\Scripts\python.exe`

## 1.2 鍏抽敭閰嶇疆鏂囦欢

- 涓氬姟鍙傛暟锛歚E:\project\auto-fanban-pre\documents\鍙傛暟瑙勮寖.yaml`
- 杩愯鏈熷弬鏁帮細`E:\project\auto-fanban-pre\documents\鍙傛暟瑙勮寖_杩愯鏈?yaml`
- 杩愯閰嶇疆浠ｇ爜锛歚E:\project\auto-fanban-pre\backend\src\config\runtime_config.py`

## 1.3 AutoCAD 涓庢墽琛屽櫒

- AutoCAD 瀹夎鐩綍锛歚D:\Program Files\AUTOCAD\AutoCAD 2022`
- `acad.exe`锛歚D:\Program Files\AUTOCAD\AutoCAD 2022\acad.exe`
- `accoreconsole.exe`锛歚D:\Program Files\AUTOCAD\AutoCAD 2022\accoreconsole.exe`
- AutoCAD Fonts锛歚D:\Program Files\AUTOCAD\AutoCAD 2022\Fonts`

## 1.4 PC3 / CTB 璺緞

- Plotters 鐩綍锛歚C:\Users\Yan\AppData\Roaming\Autodesk\AutoCAD 2022\R24.1\chs\Plotters`
- Plot Styles 鐩綍锛歚C:\Users\Yan\AppData\Roaming\Autodesk\AutoCAD 2022\R24.1\chs\Plotters\Plot Styles`
- 褰撳墠涓氬姟 PC3锛堝繀椤诲瓨鍦級锛歚C:\Users\Yan\AppData\Roaming\Autodesk\AutoCAD 2022\R24.1\chs\Plotters\鎵撳嵃PDF2.pc3`
- 褰撳墠 CTB锛歚C:\Users\Yan\AppData\Roaming\Autodesk\AutoCAD 2022\R24.1\chs\Plotters\Plot Styles\fanban_monochrome.ctb`
- AutoCAD 榛樿鍙彂鐜?PC3锛堣В鏋愬櫒鍙傝€冿級锛歚C:\Users\Yan\AppData\Roaming\Autodesk\AutoCAD 2022\R24.1\chs\Plotters\DWG To PDF.pc3`

## 1.5 妯″潡5鑴氭湰涓?.NET 妗ユ帴

- CAD 鑴氭湰鐩綍锛歚E:\project\auto-fanban-pre\backend\src\cad\scripts`
- LISP 涓昏剼鏈細`E:\project\auto-fanban-pre\backend\src\cad\scripts\module5_cad_executor.lsp`
- SCR 寮曞鑴氭湰锛歚E:\project\auto-fanban-pre\backend\src\cad\scripts\module5_bootstrap.scr`
- .NET 椤圭洰锛歚E:\project\auto-fanban-pre\backend\src\cad\dotnet\Module5CadBridge\Module5CadBridge.csproj`
- .NET DLL锛堣繍琛屾椂鍔犺浇锛夛細`E:\project\auto-fanban-pre\backend\src\cad\dotnet\Module5CadBridge\bin\Release\net48\Module5CadBridge.dll`

## 1.6 浠诲姟涓棿浜х墿璺緞

- 浠诲姟鏍圭洰褰曪細`E:\project\auto-fanban-pre\storage\jobs`
- 妯″潡5杩愯鏃朵复鏃舵牴鐩綍锛歚C:\Users\Yan\AppData\Local\Temp\fanban_module5_cad_tasks`
- 姣忔浠诲姟浼氱敓鎴愶細
  - `task.json`
  - `result.json`
  - `module5_trace.log`
  - `accoreconsole.log`
  - `cad_stage_output\*.pdf/*.dwg`

---

## 2) 褰撳墠涓绘祦绋嬶紙鎸変唬鐮佺湡瀹炲疄鐜帮紝涓嶆寜鍘嗗彶鏂囨。鎯宠薄锛?
## 2.1 鎬讳綋涓ら樁娈?
1. `split_only`
- 鍏ュ彛锛歚CADDXFExecutor.execute_source_dxf()`
- 浣滅敤锛氭寜 frame/sheet_set 閫夐泦骞?WBLOCK锛屼骇鍑?split DWG锛堜笉鍦ㄦ闃舵鍒ゆ渶缁堟垚璐ワ級銆?
2. `plot_window_only` 鎴?`plot_from_split_dwg`
- 榛樿涓昏矾寰勶細`plot_window_only`锛堜粠鍘熷 source DWG 绐楀彛鎵归噺鎵撳嵃锛夈€?- 澶辫触鍥為€€锛歚plot_from_split_dwg`锛堜粠 split DWG 鎵撳嵃锛夈€?
## 2.2 寮曟搸浼樺厛绾?
- 閫夋嫨寮曟搸锛歚module5_export.selection.engine=dotnet`
- 鎵撳嵃寮曟搸锛歚module5_export.output.plot_engine=dotnet`
- .NET 鍥為€€ LISP锛歚module5_export.dotnet_bridge.fallback_to_lisp_on_error=true`

鍒ゅ畾鍘熷垯锛?- 鍙 .NET 鎴愬姛锛岀粨鏋滃嵆涓轰富缁撴灉銆?- 鍙湁 .NET 鎶涢敊涓斿厑璁稿洖閫€鏃讹紝鎵嶅垏鎹㈠埌 LISP銆?
## 2.3 A4 鎴愮粍鎵撳嵃鍏抽敭鐐?
- 澶氶〉鎵撳嵃鐢?`.NET PlotEngine` 缁熶竴杈撳嚭澶氶〉 PDF锛坄PLOT_MULTIPAGE_USED`锛夈€?- 姣忛〉绐楀彛鏉ヨ嚜 `sheet_set.pages[].bbox/vertices`銆?- 椤甸潰鏂瑰悜鐢卞浘妗嗗楂樺叧绯诲喅瀹氾紙`W>H=landscape锛屽惁鍒?portrait`锛夛紝鏃嬭浆鐢卞獟浣撴柟鍚戜笌鐩爣鏂瑰悜宸紓鍐冲畾銆?
---

## 3) 褰撳墠鐢熸晥閰嶇疆锛堟牳蹇冨弬鏁帮級

鏁版嵁鏉ユ簮锛歚documents/鍙傛暟瑙勮寖_杩愯鏈?yaml` + `runtime_config.py`

- `module5_export.cad_runner.accoreconsole_exe = D:\Program Files\AUTOCAD\AutoCAD 2022\accoreconsole.exe`
- `module5_export.cad_runner.script_dir = E:\project\auto-fanban-pre\backend\src\cad\scripts`
- `module5_export.dotnet_bridge.dll_path = E:\project\auto-fanban-pre\backend\src\cad\dotnet\Module5CadBridge\bin\Release\net48\Module5CadBridge.dll`
- `module5_export.plot.pc3_name = 鎵撳嵃PDF2.pc3`
- `module5_export.plot.ctb_name = fanban_monochrome.ctb`
- `module5_export.plot.center_plot = false`
- `module5_export.plot.plot_offset_mm = {x:0.0, y:0.0}`
- `module5_export.plot.margins_mm = {top:0, bottom:0, left:0, right:0}`
- `module5_export.plot.scale_mode = manual_integer_from_geometry`
- `module5_export.plot.scale_integer_rounding = round`
- `module5_export.output.plot_preferred_area = window`
- `module5_export.output.plot_fallback_area = none`
- `module5_export.output.plot_session_mode = per_source_batch`
- `module5_export.output.plot_from_source_window_enabled = true`
- `module5_export.output.plot_fallback_to_split_on_failure = true`

---

## 4) AI 缁存姢鏍囧噯鎵ц姝ラ锛堢収鎶勫嵆鍙窇锛?
## 4.1 棰勬鏌ワ紙璺緞/鐜锛?
1. 鏍￠獙鍏抽敭鏂囦欢瀛樺湪锛?- `accoreconsole.exe`
- `鎵撳嵃PDF2.pc3`
- `fanban_monochrome.ctb`
- `Module5CadBridge.dll`
- `module5_cad_executor.lsp`

2. 鏍￠獙 Python 鐜锛?- 浣跨敤 `E:\project\auto-fanban-pre\backend\.venv\Scripts\python.exe`

3. 鏍￠獙閰嶇疆璇诲彇锛?- 宸ヤ綔鐩綍蹇呴』鍦ㄤ粨搴撴牴 `E:\project\auto-fanban-pre`銆?
## 4.2 缂栬瘧 .NET锛堟敼杩?C# 蹇呭仛锛?
```powershell
"E:\project\auto-fanban-pre\Dependency Library\.dotnet\sdk-local\dotnet.exe" build E:\project\auto-fanban-pre\backend\src\cad\dotnet\Module5CadBridge\Module5CadBridge.csproj -c Release
```

## 4.3 杩愯鏍锋湰鍥炲綊锛堟渶灏忛泦锛?
```powershell
E:\project\auto-fanban-pre\backend\.venv\Scripts\python.exe E:\project\auto-fanban-pre\tools\run_dwg_split_only.py "E:\project\auto-fanban-pre\test\dwg\2016浠跨湡鍥?dwg" --project-no 2016
E:\project\auto-fanban-pre\backend\.venv\Scripts\python.exe E:\project\auto-fanban-pre\tools\run_dwg_split_only.py "E:\project\auto-fanban-pre\test\dwg\1818浠跨湡鍥?dwg" --project-no 1818
```

## 4.4 蹇呮煡杈撳嚭

- `storage/jobs/<job_id>/output/drawings/*.pdf/*.dwg` 鏁伴噺鍖归厤銆?- `storage/jobs/<job_id>/work/cad_tasks/*/module5_trace.log` 涓細
  - `PLOT_FROM_SOURCE_WINDOW` 鎴?`PLOT_FROM_SPLIT_DWG`
  - `target_orientation/media_orientation/rotate`
  - `media=...`锛堟槸鍚﹀懡涓鏈熺焊寮犲悕锛?
---

## 5) 鏃ュ織瀹氫綅瑙勮寖锛圓I 璇绘棩蹇楀繀椤绘寜杩欎釜椤哄簭锛?
1. 鍏堢湅浠诲姟姹囨€?JSON锛堝懡浠よ緭鍑轰腑鐨?`job_id`锛夈€?2. 鐪?`storage/jobs/<job_id>/work/cad_tasks/*/result.json`銆?3. 鐪?`storage/jobs/<job_id>/work/cad_tasks/*/module5_trace.log`銆?4. 鑻ユ槸绐楀彛鎵归噺璺緞锛屽啀鐪嬶細
- `C:\Users\Yan\AppData\Local\Temp\fanban_module5_cad_tasks\<task_id>\plot_tasks\<subtask>\module5_trace.log`

鍏抽敭鍏抽敭璇嶏細
- `[DOTNET][PLOT][CFG]`
- `[DOTNET][PLOT][BUILD]`
- `[DOTNET][PLOT][MULTI]`
- `PLOT_FROM_SOURCE_WINDOW`
- `PLOT_FROM_SPLIT_DWG`
- `MEDIA_NOT_MATCHED`

---

## 6) 甯歌闂 -> 鏍瑰洜 -> 澶勭悊鍔ㄤ綔

## 6.1 鈥淧DF 鐪嬭捣鏉ュ儚绐楀彛閫夐敊浜嗏€?
甯歌鏍瑰洜锛?- 涓嶆槸绐楀彛妗嗛敊锛岃€屾槸鍛戒腑濯掍綋鍙墦鍗板尯鍩熻繃灏忥紙渚嬪鍛戒腑 `ISO_A4` 鑰岄潪涓氬姟 PC3 绾稿紶鍚嶏級銆?
澶勭悊锛?1. 鏌?`BUILD` 琛岀殑 `media=...`銆?2. 瀵圭収 `鍙傛暟瑙勮寖.yaml` 绾稿紶鍚嶇О鏄犲皠銆?3. 鑻ュ懡涓敊璇獟浣擄紝鍏堜慨鍚嶇О鍖归厤浼樺厛绾э紝鍐嶅璺戙€?
## 6.2 鈥淎4 鏂瑰悜涓嶅锛堝簲绔栧悜鍗磋妯悜锛夆€?
鏍瑰洜锛?- 鐩爣鏂瑰悜涓庡獟浣撴柟鍚戝垽瀹?鏃嬭浆閫昏緫鍐茬獊銆?
澶勭悊锛?1. 鐪?`target_orientation` 涓?`media_orientation`銆?2. 鐪?`rotate=0/90` 鏄惁绗﹀悎 `W>H` 瑙勫垯銆?3. 鑻ヤ笉绗﹀悎锛屾敼 `PlotEngine.cs` 涓柟鍚戝垽瀹氫笌鏃嬭浆閫昏緫锛屼笉鏀逛笟鍔℃鏋惰瘑鍒€昏緫銆?
## 6.3 鈥滃ぇ閲?PLOT 澶辫触鈥?
鏍瑰洜鏂瑰悜锛?- PC3 璺緞涓嶅彲杈俱€?- 绾稿紶鍚嶅湪 PC3 涓笉瀛樺湪銆?- AutoCAD 鐜鏈姞杞芥纭?Plotters銆?
澶勭悊锛?1. 鍏堢湅 `[DOTNET][PLOT][CFG] pc3_resolved_path=`銆?2. 鍐嶇湅 `[DOTNET][PLOT][MEDIA]` 鐨?available sample銆?3. 鍐嶇‘璁?`鎵撳嵃PDF2.pc3` 閲岀焊寮犲悕绉颁笌鏄犲皠鏄惁涓€鑷淬€?
## 6.4 鈥?NET 涓?LISP 娣风敤瀵艰嚧缁撴灉涓嶇ǔ瀹氣€?
澶勭悊锛?- 鏄庣‘涓€杞换鍔″彧鐪嬫渶缁?flags锛?  - 鏈?`DOTNET_TO_LISP_FALLBACK` 璇存槑纭疄鍙戠敓鍥為€€銆?  - 鏃犺鏍囪鍗充负绾?.NET 璺緞銆?
---

## 7) 绂佹浜嬮」锛堢淮鎶ょ孩绾匡級

- 绂佹鐩存帴鍒犻櫎鎴栭潤榛樼粫杩囨姤閿欓€昏緫銆?- 绂佹鏈粡楠岃瘉灏辨敼 `plot_preferred_area/window` 璇箟銆?- 绂佹鎶娾€滃悕绉板尮閰嶇焊寮犫€濋€€鍥炩€滅函灏哄杩戜技鍖归厤鈥濄€?- 绂佹鍦ㄦ湭鏌?trace 鐨勬儏鍐典笅鍒ゆ柇鈥滅獥鍙ｉ敊/姣斾緥閿欌€濄€?
---

## 8) 楠屾敹鏍囧噯锛堟敼鍔ㄥ畬鎴愬悗蹇呴』鍏ㄩ儴婊¤冻锛?
- `2016浠跨湡鍥綻銆乣1818浠跨湡鍥綻 鍧囧彲璺戦€氾紝`pdf_count == dwg_count`锛堟寜鏍锋湰棰勬湡锛夈€?- A4 澶氶〉 PDF 椤垫暟姝ｇ‘锛屾柟鍚戜笌鍥炬瀹介珮鍏崇郴涓€鑷淬€?- trace 涓彲鐪嬪埌瀹屾暣 BUILD 璇佹嵁锛歚media + orientation + rotate + bbox_wcs/bbox_dcs`銆?- 鏈嚭鐜扳€滃帇閿欓€氳繃鈥濓細鎵€鏈夊け璐ラ兘鏈夊叿浣?flag 鎴?error 鏂囨湰銆?
---

## 9) 缁存姢璁板綍妯℃澘锛堟瘡娆℃敼鍔ㄥ悗蹇呴』琛ワ級

鎸変互涓嬫ā鏉块檮鍦ㄦ彁浜よ鏄庢垨浠诲姟璁板綍锛?
```text
[妯″潡5缁存姢璁板綍]
鏃ユ湡:
鎿嶄綔鑰?
鏀瑰姩鏂囦欢:
鏀瑰姩鐩爣:
鍏抽敭璺緞鏄惁鍙樺寲(鏄?鍚?:
2016鍥炲綊缁撴灉:
1818鍥炲綊缁撴灉:
鏄惁鍙戠敓DOTNET_TO_LISP_FALLBACK:
閬楃暀闂:
```

---

## 10) 蹇€熷懡浠ゆ竻鍗曪紙鍙洿鎺ュ鍒讹級

```powershell
# 1) 缂栬瘧 .NET 妗ユ帴
cd /d E:\project\auto-fanban-pre
"Dependency Library\.dotnet\sdk-local\dotnet.exe" build backend\src\cad\dotnet\Module5CadBridge\Module5CadBridge.csproj -c Release

# 2) 璺?2016
backend\.venv\Scripts\python.exe tools\run_dwg_split_only.py "test\dwg\2016浠跨湡鍥?dwg" --project-no 2016

# 3) 璺?1818
backend\.venv\Scripts\python.exe tools\run_dwg_split_only.py "test\dwg\1818浠跨湡鍥?dwg" --project-no 1818

# 4) 鏌ョ湅鏈€鏂颁复鏃朵换鍔＄洰褰?powershell -NoProfile -Command "Get-ChildItem $env:TEMP\fanban_module5_cad_tasks -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 3 FullName,LastWriteTime"
```

---

> 鏈枃浠舵槸妯″潡5褰撳墠鏈哄櫒鐨勨€滄墽琛屽疄鍐垫爣鍑嗘枃妗ｂ€濄€?> 
> 鍚庣画浠讳綍 AI 缁存姢閮藉簲鍏堝鐓х 1 绔犺矾寰勶紝鍐嶆墽琛岀 4 绔犳祦绋嬶紝鍐嶆寜绗?8 绔犻獙鏀躲€?

